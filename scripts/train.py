#!/usr/bin/env python3
"""
Training script for SelectiveMagnoViT model.
"""

import argparse
import logging
import sys
from pathlib import Path

import torch

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from selective_magno_vit.utils.config import Config
from selective_magno_vit.training.trainer import Trainer
from selective_magno_vit.data.dataset import get_dataloaders
from selective_magno_vit.models.selective_vit import SelectiveMagnoViT
from selective_magno_vit.utils.logging import setup_logging


def parse_args():
    parser = argparse.ArgumentParser(description="Train SelectiveMagnoViT")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/base_config.yaml",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--magno_dir",
        type=str,
        help="Override magno image directory"
    )
    parser.add_argument(
        "--lines_dir",
        type=str,
        help="Override line drawing directory"
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        help="Override output directory"
    )
    parser.add_argument(
        "--patch_percentage",
        type=float,
        help="Override patch percentage"
    )
    parser.add_argument(
        "--batch_size",
        type=int,
        help="Override batch size"
    )
    parser.add_argument(
        "--epochs",
        type=int,
        help="Override number of epochs"
    )
    parser.add_argument(
        "--resume",
        type=str,
        help="Path to checkpoint to resume from"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Load configuration
    config = Config(args.config)
    
    # Override with command line arguments
    if args.magno_dir:
        config.set('data.magno_dir', args.magno_dir)
    if args.lines_dir:
        config.set('data.lines_dir', args.lines_dir)
    if args.output_dir:
        config.set('output.checkpoint_dir', args.output_dir)
    if args.patch_percentage:
        config.set('model.patch_percentage', args.patch_percentage)
    if args.batch_size:
        config.set('training.batch_size', args.batch_size)
    if args.epochs:
        config.set('training.epochs', args.epochs)
    
    # Setup logging
    logger = setup_logging(
        log_dir=config.get('output.logs_dir'),
        log_level=config.get('logging.level', 'INFO')
    )
    
    logger.info(f"Starting training with config: {args.config}")
    logger.info(f"PyTorch version: {torch.__version__}")
    logger.info(f"CUDA available: {torch.cuda.is_available()}")
    
    # Setup device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using device: {device}")
    
    # Create dataloaders
    train_loader, val_loader = get_dataloaders(config)
    num_classes = train_loader.dataset.num_classes
    logger.info(f"Number of classes: {num_classes}")
    logger.info(f"Training samples: {len(train_loader.dataset)}")
    logger.info(f"Validation samples: {len(val_loader.dataset)}")
    
    # Create model
    model = SelectiveMagnoViT(
        patch_percentage=config.get('model.patch_percentage'),
        num_classes=num_classes,
        img_size=config.get('model.img_size'),
        patch_size=config.get('model.patch_size'),
        vit_model_name=config.get('model.vit_model_name'),
        selector_config=config.get('model.selector')
    ).to(device)
    
    logger.info(f"Model created with {sum(p.numel() for p in model.parameters())} parameters")
    
    # Create trainer
    trainer = Trainer(
        model=model,
        train_loader=train_loader,
        val_loader=val_loader,
        config=config,
        device=device,
        logger=logger
    )
    
    # Resume from checkpoint if specified
    if args.resume:
        trainer.load_checkpoint(args.resume)
        logger.info(f"Resumed from checkpoint: {args.resume}")
    
    # Train
    try:
        best_accuracy = trainer.train()
        logger.info(f"Training completed! Best validation accuracy: {best_accuracy:.4f}")
    except KeyboardInterrupt:
        logger.info("Training interrupted by user")
        trainer.save_checkpoint("interrupted_checkpoint.pth")
    except Exception as e:
        logger.error(f"Training failed with error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()