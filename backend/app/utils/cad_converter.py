"""
CAD file conversion utilities for STEP to glTF.
Handles STEP file conversion to glTF format using pythonocc-core.
"""

import asyncio
import json
import logging
import os
import struct
from pathlib import Path
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


async def convert_step_to_gltf(
    step_file_path: str,
    output_gltf_path: str,
    linear_deflection: float = 0.05,
    angular_deflection: float = 0.3,
) -> bool:
    """
    Convert STEP CAD file to glTF format using pythonocc-core.

    Args:
        step_file_path: Path to input STEP file
        output_gltf_path: Path to output glTF binary file
        linear_deflection: Mesh quality parameter (lower = higher quality, slower)
        angular_deflection: Angular deflection for meshing

    Returns:
        True if conversion successful, False otherwise
    """
    try:
        # Import here to handle potential installation issues gracefully
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE
        from OCC.Core.BRep import BRep_Tool

        # Verify input file exists
        if not os.path.exists(step_file_path):
            logger.error(f"Input STEP file not found: {step_file_path}")
            return False

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_gltf_path), exist_ok=True)

        # Run conversion in thread pool to avoid blocking async loop
        success = await asyncio.to_thread(
            _perform_conversion,
            step_file_path,
            output_gltf_path,
            linear_deflection,
            angular_deflection,
        )

        if success:
            logger.info(
                f"Successfully converted {step_file_path} to {output_gltf_path}"
            )
        else:
            logger.error(f"Conversion failed for {step_file_path}")

        return success

    except ImportError as e:
        logger.warning(f"pythonocc-core not available: {e}")
        # Try fallback: use trimesh if available
        try:
            import trimesh
            logger.info("Attempting fallback conversion with trimesh...")
            mesh = trimesh.load(step_file_path)
            mesh.export(output_gltf_path)
            logger.info(f"Fallback: Converted with trimesh to {output_gltf_path}")
            return True
        except Exception as trimesh_error:
            logger.error(f"Trimesh fallback also failed: {trimesh_error}")
            return False
    except Exception as e:
        logger.error(f"Unexpected error during conversion: {e}", exc_info=True)
        return False


def _perform_conversion(
    step_file_path: str,
    output_gltf_path: str,
    linear_deflection: float,
    angular_deflection: float,
) -> bool:
    """
    Perform the actual STEP to glTF conversion (runs in thread pool).

    Args:
        step_file_path: Input STEP file path
        output_gltf_path: Output glTF file path
        linear_deflection: Mesh quality parameter
        angular_deflection: Angular deflection for meshing

    Returns:
        True if successful
    """
    try:
        from OCC.Core.STEPControl import STEPControl_Reader
        from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_COMPOUND
        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.TopTools import TopTools_ListOfShape
        from OCC.Core.ShapeFix import ShapeFix_Wire
        from OCC.Core.ShapeAnalysis import ShapeAnalysis_Wire
        from OCC.Core.BRepBuilderAPI import BRepBuilderAPI_MakePolygon

        # Read STEP file
        reader = STEPControl_Reader()
        status = reader.ReadFile(step_file_path)

        if status == 0:  # Status code 0 means failure
            logger.error(f"Failed to read STEP file: {step_file_path}")
            return False

        # Translate the file
        reader.TransferRoots()
        shape = reader.OneShape()

        if shape.IsNull():
            logger.error("No valid shape found in STEP file")
            return False

        # Create a mesh from the shape with better quality
        mesh = BRepMesh_IncrementalMesh(shape, linear_deflection, False, angular_deflection, True)
        mesh.Perform()

        if not mesh.IsDone():
            logger.error("Failed to create mesh from shape")
            return False

        # Extract mesh data including normals
        vertices, normals, faces = _extract_mesh_data_with_normals(shape)

        if not vertices or not faces:
            logger.error("Failed to extract mesh data from shape")
            return False

        # Write glTF binary file with normals
        _write_gltf_binary(output_gltf_path, vertices, normals, faces)

        return True

    except Exception as e:
        logger.error(f"Error in conversion process: {e}", exc_info=True)
        return False


def _extract_mesh_data_with_normals(shape) -> Tuple[List[float], List[float], List[int]]:
    """
    Extract vertices, normals, and faces from OCP shape.

    Args:
        shape: OCP shape object

    Returns:
        Tuple of (vertices list, normals list, faces list)
    """
    try:
        from OCC.Core.TopExp import TopExp_Explorer
        from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_REVERSED
        from OCC.Core.Poly import Poly_Triangulation
        from OCC.Core.BRep import BRep_Tool
        from OCC.Core.TopLoc import TopLoc_Location
        from OCC.Core.gp import gp_Vec

        vertices = []
        normals = []
        faces = []
        vertex_offset = 0

        # Iterate through all faces
        explorer = TopExp_Explorer(shape, TopAbs_FACE)

        while explorer.More():
            face = explorer.Current()

            # Get triangulation for this face
            location = TopLoc_Location()
            triangulation = BRep_Tool.Triangulation(face, location)

            if triangulation is not None:
                # Check face orientation for normal direction
                face_reversed = face.Orientation() == TopAbs_REVERSED

                # Get transformation matrix
                transform = location.Transformation()

                # Extract vertices and compute normals
                nb_nodes = triangulation.NbNodes()
                nb_triangles = triangulation.NbTriangles()

                # Initialize per-vertex normals to zero
                vertex_normals = [[0.0, 0.0, 0.0] for _ in range(nb_nodes)]

                # First pass: accumulate face normals to vertices
                for i in range(1, nb_triangles + 1):
                    triangle = triangulation.Triangle(i)
                    n1, n2, n3 = triangle.Get()

                    # Get vertex positions
                    p1 = triangulation.Node(n1)
                    p2 = triangulation.Node(n2)
                    p3 = triangulation.Node(n3)

                    # Apply transformation
                    p1 = p1.Transformed(transform)
                    p2 = p2.Transformed(transform)
                    p3 = p3.Transformed(transform)

                    # Compute face normal
                    v1 = gp_Vec(p1, p2)
                    v2 = gp_Vec(p1, p3)
                    face_normal = v1.Crossed(v2)

                    if face_normal.Magnitude() > 1e-10:
                        face_normal.Normalize()

                        # Flip normal if face is reversed
                        if face_reversed:
                            face_normal.Reverse()

                        # Accumulate to vertex normals
                        for idx in [n1, n2, n3]:
                            vertex_normals[idx - 1][0] += face_normal.X()
                            vertex_normals[idx - 1][1] += face_normal.Y()
                            vertex_normals[idx - 1][2] += face_normal.Z()

                # Normalize accumulated normals
                for vn in vertex_normals:
                    mag = (vn[0]**2 + vn[1]**2 + vn[2]**2) ** 0.5
                    if mag > 1e-10:
                        vn[0] /= mag
                        vn[1] /= mag
                        vn[2] /= mag
                    else:
                        vn[0], vn[1], vn[2] = 0.0, 1.0, 0.0  # Default up normal

                # Second pass: extract transformed vertices and normals
                for i in range(1, nb_nodes + 1):
                    node = triangulation.Node(i)
                    # Apply transformation
                    node = node.Transformed(transform)
                    vertices.extend([node.X(), node.Y(), node.Z()])
                    normals.extend(vertex_normals[i - 1])

                # Extract triangles with correct winding
                for i in range(1, nb_triangles + 1):
                    triangle = triangulation.Triangle(i)
                    n1, n2, n3 = triangle.Get()

                    if face_reversed:
                        # Reverse winding order for reversed faces
                        faces.extend([n1 - 1 + vertex_offset, n3 - 1 + vertex_offset, n2 - 1 + vertex_offset])
                    else:
                        faces.extend([n1 - 1 + vertex_offset, n2 - 1 + vertex_offset, n3 - 1 + vertex_offset])

                vertex_offset += nb_nodes

            explorer.Next()

        return vertices, normals, faces

    except Exception as e:
        logger.error(f"Error extracting mesh data: {e}", exc_info=True)
        return [], [], []


def _write_gltf_binary(
    output_path: str, vertices: List[float], normals: List[float], faces: List[int]
) -> None:
    """
    Write mesh data to glTF binary (.glb) file with normals.

    Args:
        output_path: Output file path
        vertices: List of vertex coordinates (flat array)
        normals: List of normal vectors (flat array)
        faces: List of face indices (flat array)
    """
    # Create minimal glTF 2.0 binary file
    # Based on glTF 2.0 specification

    # Prepare mesh data
    vertex_count = len(vertices) // 3
    face_count = len(faces) // 3

    # Calculate bounds for accessor
    if vertices:
        xs = [vertices[i] for i in range(0, len(vertices), 3)]
        ys = [vertices[i] for i in range(1, len(vertices), 3)]
        zs = [vertices[i] for i in range(2, len(vertices), 3)]

        min_pos = [min(xs), min(ys), min(zs)]
        max_pos = [max(xs), max(ys), max(zs)]
    else:
        min_pos = [0, 0, 0]
        max_pos = [0, 0, 0]

    # Calculate byte lengths
    vertex_byte_length = len(vertices) * 4
    normal_byte_length = len(normals) * 4
    index_byte_length = len(faces) * 4

    # Ensure 4-byte alignment for each buffer view
    normal_offset = vertex_byte_length
    index_offset = normal_offset + normal_byte_length

    # Create minimal glTF structure with normals
    gltf_json = {
        "asset": {"generator": "PLM2-System", "version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": 0,
                            "NORMAL": 1
                        },
                        "indices": 2,
                        "material": 0,
                    }
                ]
            }
        ],
        "materials": [
            {
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.7, 0.7, 0.75, 1.0],
                    "metallicFactor": 0.3,
                    "roughnessFactor": 0.6
                },
                "doubleSided": False
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,  # FLOAT
                "count": vertex_count,
                "type": "VEC3",
                "min": min_pos,
                "max": max_pos,
            },
            {
                "bufferView": 1,
                "componentType": 5126,  # FLOAT
                "count": vertex_count,
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "componentType": 5125,  # UNSIGNED_INT
                "count": len(faces),
                "type": "SCALAR",
            },
        ],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": vertex_byte_length,
                "target": 34962,  # ARRAY_BUFFER
            },
            {
                "buffer": 0,
                "byteOffset": normal_offset,
                "byteLength": normal_byte_length,
                "target": 34962,  # ARRAY_BUFFER
            },
            {
                "buffer": 0,
                "byteOffset": index_offset,
                "byteLength": index_byte_length,
                "target": 34963,  # ELEMENT_ARRAY_BUFFER
            },
        ],
        "buffers": [{"byteLength": vertex_byte_length + normal_byte_length + index_byte_length}],
    }

    # Serialize JSON
    json_str = json.dumps(gltf_json, separators=(",", ":"))
    json_bytes = json_str.encode("utf-8")

    # Pad JSON to 4-byte boundary
    json_padding = (4 - (len(json_bytes) % 4)) % 4
    json_bytes += b" " * json_padding

    # Prepare binary data
    binary_data = b""

    # Add vertex positions (float32 array)
    for v in vertices:
        binary_data += struct.pack("<f", v)

    # Add vertex normals (float32 array)
    for n in normals:
        binary_data += struct.pack("<f", n)

    # Add face indices (uint32 array)
    for f in faces:
        binary_data += struct.pack("<I", f)

    # Create GLB file
    # GLB header: 12 bytes (magic 4 + version 4 + length 4)
    # JSON chunk: 8 bytes header + json_bytes
    # Binary chunk: 8 bytes header + binary_data
    magic = b"glTF"
    version = struct.pack("<I", 2)
    total_size = 12 + 8 + len(json_bytes) + 8 + len(binary_data)
    file_size = struct.pack("<I", total_size)

    # JSON chunk
    json_chunk_size = struct.pack("<I", len(json_bytes))
    json_chunk_type = b"JSON"

    # Binary chunk
    binary_chunk_size = struct.pack("<I", len(binary_data))
    binary_chunk_type = b"BIN\x00"

    # Write GLB file
    with open(output_path, "wb") as f:
        f.write(magic)
        f.write(version)
        f.write(file_size)
        f.write(json_chunk_size)
        f.write(json_chunk_type)
        f.write(json_bytes)
        f.write(binary_chunk_size)
        f.write(binary_chunk_type)
        f.write(binary_data)

    logger.info(f"glTF file written to {output_path}")
