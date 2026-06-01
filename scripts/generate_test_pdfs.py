#!/usr/bin/env python3
"""
Generate test PDFs for benchmarking by copying existing PDFs.

This creates variations of existing PDFs to reach a target count.
Usage: python scripts/generate_test_pdfs.py --target 100
"""

import argparse
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def generate_test_pdfs(pdf_dir: Path, target_count: int) -> int:
    """
    Generate test PDFs by copying and renaming existing ones.

    Args:
        pdf_dir: Directory containing PDFs
        target_count: Target number of PDFs

    Returns:
        Total number of PDFs created
    """
    existing_pdfs = sorted(list(pdf_dir.glob("*.pdf")))
    current_count = len(existing_pdfs)

    if current_count >= target_count:
        logger.info(f"Already have {current_count} PDFs (target: {target_count})")
        return current_count

    needed = target_count - current_count
    logger.info(f"Need to create {needed} more PDFs (have {current_count}, target {target_count})")

    # Copy PDFs in rotation
    created = 0
    copy_index = 0

    for i in range(needed):
        src_pdf = existing_pdfs[copy_index % len(existing_pdfs)]

        # Create new filename with copy index
        new_filename = f"benchmark_copy_{i + 1:03d}.pdf"
        dst_pdf = pdf_dir / new_filename

        try:
            shutil.copy2(src_pdf, dst_pdf)
            created += 1
            copy_index += 1

            if (i + 1) % 10 == 0:
                logger.info(f"Created {created} copies...")
        except Exception as e:
            logger.error(f"Failed to copy {src_pdf}: {e}")

    total = current_count + created
    logger.info(f"Done. Total PDFs: {total}")
    return total


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Generate test PDFs for benchmarking")
    parser.add_argument(
        "--target",
        type=int,
        default=100,
        help="Target number of PDFs (default: 100)",
    )
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=None,
        help="PDF directory (default: data/raw)",
    )

    args = parser.parse_args()

    pdf_dir = args.pdf_dir or (Path(__file__).parent.parent / "data" / "raw")
    pdf_dir.mkdir(parents=True, exist_ok=True)

    generate_test_pdfs(pdf_dir, args.target)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
