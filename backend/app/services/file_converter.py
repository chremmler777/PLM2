"""Convert 3D file formats to glTF for web viewing."""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def convert_step_to_gltf_async(input_file_path: str, output_file_path: str) -> bool:
    """
    Asynchronously convert STEP file to glTF using pythonocc-core.

    Args:
        input_file_path: Path to STEP file
        output_file_path: Path for output glTF file

    Returns:
        True if successful, False otherwise
    """
    try:
        from app.utils.cad_converter import convert_step_to_gltf

        # Run async conversion
        result = await convert_step_to_gltf(input_file_path, output_file_path)
        return result

    except ImportError:
        logger.error("pythonocc-core not installed. Cannot convert STEP files.")
        return False
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        return False


def create_sample_gltf(input_file_path: str, output_file_path: str) -> bool:
    """
    Convert STEP/CATIA file to glTF.
    Tries proper conversion first, falls back gracefully.
    """
    try:
        # For synchronous context, we need to run the async function
        # This should be called from an async context, so use asyncio.run as fallback
        try:
            # Try to get the event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, this shouldn't happen in this function
                # But if it does, create a new task
                task = asyncio.create_task(convert_step_to_gltf_async(input_file_path, output_file_path))
                # This won't work here, so fall through to sync conversion
                raise RuntimeError("Cannot use async in sync context")
        except RuntimeError:
            pass

        # Try sync conversion first
        try:
            from app.utils.cad_converter import convert_step_to_gltf
            import asyncio

            # Create a new event loop for this thread
            result = asyncio.run(convert_step_to_gltf(input_file_path, output_file_path))
            return result
        except Exception as e:
            logger.warning(f"Sync conversion failed: {e}")
            return False

    except Exception as e:
        logger.error(f"Failed to create glTF: {e}")
        return False
