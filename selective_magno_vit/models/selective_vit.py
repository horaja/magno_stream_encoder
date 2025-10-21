"""
SelectiveMagnoViT: Vision Transformer with line drawing-guided selective patch processing.

This module implements the main model that combines:
1. Patch importance scoring based on line drawings
2. Spatial threshold-based patch selection
3. Vision Transformer processing on selected patches
"""

import torch
import torch.nn as nn
import timm
from typing import Optional, Dict

from .patch_scorer import PatchImportanceScorer
from .patch_selecter import SpatialThresholdSelector


class SelectiveMagnoViT(nn.Module):
    """
    SelectiveMagnoViT: A Vision Transformer that selectively processes patches
    based on importance scores derived from line drawings.

    The model works in three stages:
    1. Score patches using line drawing density (PatchImportanceScorer)
    2. Select important patches using spatial threshold strategy (SpatialThresholdSelector)
    3. Process selected patches through a Vision Transformer

    Args:
        patch_percentage: Fraction of patches to select (0, 1]
        num_classes: Number of output classes for classification
        img_size: Input image size (assumes square images)
        patch_size: Size of each patch
        vit_model_name: Name of the pre-trained ViT model from timm
        selector_config: Configuration dict for the patch selector
        embed_dim: Embedding dimension (if None, uses ViT default)
        pretrained: Whether to use pretrained ViT weights
    """

    def __init__(
        self,
        patch_percentage: float = 0.4,
        num_classes: int = 10,
        img_size: int = 64,
        patch_size: int = 4,
        vit_model_name: str = 'vit_tiny_patch16_224.augreg_in21k',
        selector_config: Optional[Dict] = None,
        embed_dim: Optional[int] = None,
        pretrained: bool = True
    ):
        super().__init__()

        # Validate inputs
        if not 0 < patch_percentage <= 1.0:
            raise ValueError(f"patch_percentage must be in (0, 1], got {patch_percentage}")
        if img_size % patch_size != 0:
            raise ValueError(f"img_size ({img_size}) must be divisible by patch_size ({patch_size})")

        # Store configuration
        self.patch_percentage = patch_percentage
        self.num_classes = num_classes
        self.img_size = img_size
        self.patch_size = patch_size
        self.vit_model_name = vit_model_name

        # Load ViT backbone from timm
        self.vit = timm.create_model(vit_model_name, pretrained=pretrained)

        # Get embedding dimension from loaded model
        if embed_dim is None:
            embed_dim = self.vit.embed_dim
        self.embed_dim = embed_dim

        # Replace patch embedding layer for custom image size
        # This allows us to work with images of different sizes than the pretrained model
        self.vit.patch_embed = timm.models.vision_transformer.PatchEmbed(
            img_size=img_size,
            patch_size=patch_size,
            in_chans=3,
            embed_dim=embed_dim
        )

        # Update positional embeddings for new number of patches
        num_patches = self.vit.patch_embed.num_patches
        self.vit.pos_embed = nn.Parameter(
            torch.zeros(1, num_patches + 1, embed_dim)  # +1 for CLS token
        )
        nn.init.trunc_normal_(self.vit.pos_embed, std=0.02)

        # Replace classifier head for custom number of classes
        self.vit.head = nn.Linear(embed_dim, num_classes)

        # Initialize custom modules for patch selection
        self.scorer = PatchImportanceScorer(patch_size=patch_size)

        # Setup selector with config
        if selector_config is None:
            selector_config = {}
        self.selector = SpatialThresholdSelector(
            patch_percentage=patch_percentage,
            threshold=selector_config.get('threshold', 0.3),
            gaussian_std=selector_config.get('gaussian_std', 0.25)
        )

        # Store metadata
        self.num_patches = num_patches

    def forward(self, magno_image: torch.Tensor, line_drawing: torch.Tensor) -> torch.Tensor:
        """
        Forward pass through the model.

        Args:
            magno_image: Batch of Magno-channel images of shape (B, 3, H, W)
                        These are the actual images to be processed
            line_drawing: Batch of line drawings of shape (B, 1, H, W)
                         Used to determine which patches are important

        Returns:
            Classification logits of shape (B, num_classes)
        """
        # Step 1: Score patches based on line drawing density
        patch_scores = self.scorer(line_drawing)  # (B, num_patches)

        # Step 2: Extract all patches from the Magno image
        all_patches = self.vit.patch_embed(magno_image)  # (B, num_patches, embed_dim)

        # Step 3: Select important patches using spatial threshold strategy
        # This adds positional embeddings to the selected patches
        selected_patches = self.selector(
            all_patches,
            self.vit.pos_embed,
            patch_scores,
            line_drawing
        )  # (B, k, embed_dim) where k = num_patches * patch_percentage

        # Step 4: Prepare [CLS] token with its positional embedding
        cls_token_with_pos = self.vit.cls_token + self.vit.pos_embed[:, :1, :]

        # Step 5: Combine [CLS] token with selected patches
        batch_size = magno_image.shape[0]
        full_sequence = torch.cat([
            cls_token_with_pos.expand(batch_size, -1, -1),  # (B, 1, embed_dim)
            selected_patches  # (B, k, embed_dim)
        ], dim=1)  # (B, k+1, embed_dim)

        # Step 6: Apply dropout to the full sequence
        full_sequence = self.vit.pos_drop(full_sequence)

        # Step 7: Process through transformer blocks
        x = self.vit.blocks(full_sequence)
        x = self.vit.norm(x)

        # Step 8: Extract [CLS] token output for classification
        cls_output = x[:, 0]  # (B, embed_dim)

        # Step 9: Final classification head
        logits = self.vit.head(cls_output)  # (B, num_classes)

        return logits

    @torch.no_grad()
    def get_selected_patch_indices(self, line_drawing: torch.Tensor) -> torch.Tensor:
        """
        Get indices of selected patches for visualization purposes.

        This method is useful for understanding which patches the model
        considers important for a given line drawing.

        Args:
            line_drawing: Line drawing tensor of shape (B, 1, H, W)

        Returns:
            Indices of selected patches of shape (B, k) where k is the number
            of selected patches
        """
        # Score patches
        patch_scores = self.scorer(line_drawing)

        # Calculate number of patches to select
        k = max(1, int(patch_scores.shape[1] * self.patch_percentage))

        # Get top-k indices (simple version without spatial weighting)
        _, indices = torch.topk(patch_scores, k=k, dim=1)

        return indices

    @torch.no_grad()
    def get_patch_importance_map(self, line_drawing: torch.Tensor) -> torch.Tensor:
        """
        Get 2D importance map showing patch scores.

        Useful for visualization to understand which regions of the image
        are considered important.

        Args:
            line_drawing: Line drawing tensor of shape (B, 1, H, W)

        Returns:
            Importance map of shape (B, 1, H', W') where H' = H/patch_size,
            W' = W/patch_size
        """
        # Get patch scores
        patch_scores = self.scorer(line_drawing)  # (B, num_patches)

        # Reshape to 2D grid
        num_patches_per_side = int(self.num_patches ** 0.5)
        importance_map = patch_scores.view(
            -1, 1, num_patches_per_side, num_patches_per_side
        )

        return importance_map

    def get_num_selected_patches(self) -> int:
        """Get the number of patches that will be selected."""
        return max(1, int(self.num_patches * self.patch_percentage))

    def get_model_info(self) -> Dict[str, any]:
        """Get information about the model configuration."""
        return {
            'model_name': self.__class__.__name__,
            'vit_backbone': self.vit_model_name,
            'img_size': self.img_size,
            'patch_size': self.patch_size,
            'num_patches': self.num_patches,
            'selected_patches': self.get_num_selected_patches(),
            'patch_percentage': self.patch_percentage,
            'embed_dim': self.embed_dim,
            'num_classes': self.num_classes,
            'total_params': sum(p.numel() for p in self.parameters()),
            'trainable_params': sum(p.numel() for p in self.parameters() if p.requires_grad)
        }
