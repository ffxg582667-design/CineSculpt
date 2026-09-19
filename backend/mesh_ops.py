# -*- coding: utf-8 -*-
# mesh operations: add base / scale / simplify / repair / print check
import trimesh
import numpy as np

MAX_SIZE_MM = 200.0
MIN_FEATURE_MM = 0.5

def load_mesh(path):
    return trimesh.load(path, force="mesh")

def add_base(mesh, shape="cylinder"):
    bounds = mesh.bounds
    size = bounds[1] - bounds[0]
    cx = (bounds[0][0] + bounds[1][0]) / 2.0
    cy = (bounds[0][1] + bounds[1][1]) / 2.0
    zmin = bounds[0][2]
    radius = max(size[0], size[1]) * 0.6
    height = max(size[2] * 0.1, 0.2)
    if shape == "box":
        base = trimesh.creation.box(extents=(radius * 2, radius * 2, height))
    else:
        base = trimesh.creation.cylinder(radius=radius, height=height, sections=48)
    base.apply_translation((cx, cy, zmin - height / 2.0))
    return trimesh.util.concatenate([mesh, base])

def scale_to_height(mesh, target_height_mm):
    size = mesh.bounds[1] - mesh.bounds[0]
    cur_h = size[2] if size[2] > 0 else 1.0
    factor = float(target_height_mm) / float(cur_h)
    m = mesh.copy()
    m.apply_scale(factor)
    return m

def simplify(mesh, ratio=0.5):
    try:
        target = max(4, int(len(mesh.faces) * float(ratio)))
        return mesh.simplify_quadric_decimation(target)
    except Exception as e:
        print("simplify failed:", e)
        return mesh

def repair(mesh, return_report=False):
    # comprehensive geometry repair for 3D printing
    m = mesh.copy()
    report = {"holes_before": 0, "components_removed": 0, "watertight": False}
    # 0. pre-simplify heavy meshes first, so all later steps are fast (avoids freezing)
    try:
        if len(m.faces) > 8000:
            m = m.simplify_quadric_decimation(8000)
    except Exception as e:
        print("pre-simplify failed:", e)
    # 1. merge duplicate vertices and remove degenerate/duplicate faces
    m.merge_vertices()
    try:
        m.update_faces(m.nondegenerate_faces())
        m.update_faces(m.unique_faces())
        m.remove_unreferenced_vertices()
    except Exception as e:
        print("cleanup faces failed:", e)
    # 2. remove isolated small fragments, keep only the largest connected body
    try:
        comps = m.split(only_watertight=False)
        if len(comps) > 1:
            comps = sorted(comps, key=lambda c: len(c.faces), reverse=True)
            biggest = comps[0]
            # keep components that are at least 5% of the biggest (drop tiny debris)
            keep = [c for c in comps if len(c.faces) >= max(1, len(biggest.faces) * 0.05)]
            report["components_removed"] = len(comps) - len(keep)
            m = trimesh.util.concatenate(keep) if len(keep) > 1 else biggest
    except Exception as e:
        print("split failed:", e)
    # 3. count holes before filling
    try:
        report["holes_before"] = int(len(m.facets_boundary))
    except Exception:
        pass
    # 4. fix winding/normals and fill holes (make watertight)
    try:
        trimesh.repair.fix_winding(m)
        trimesh.repair.fix_normals(m)
        trimesh.repair.fill_holes(m)
    except Exception as e:
        print("repair step failed:", e)
    report["watertight"] = bool(m.is_watertight)
    report["voxel_remeshed"] = False
    # only voxel-remesh when the mesh is badly broken (many boundary holes).
    # use a low resolution (64) so it stays fast and does not freeze the machine.
    holes = report.get("holes_before", 0)
    if not m.is_watertight and holes > 50:
        try:
            # normalize size first: tiny models (e.g. 1mm) break voxelization.
            # scale so the largest dimension is ~100 units, voxelize, then keep it.
            extent = float(max(m.extents))
            norm_scale = 100.0 / extent if extent > 0 else 1.0
            m.apply_scale(norm_scale)
            pitch = 100.0 / 64.0  # fixed pitch on normalized model = stable & fast
            vox = m.voxelized(pitch=pitch).fill()
            remeshed = vox.marching_cubes
            if remeshed is not None and len(remeshed.faces) > 0:
                # simplification is optional polish; never let it break the watertight result
                try:
                    if len(remeshed.faces) > 20000:
                        remeshed = remeshed.simplify_quadric_decimation(20000)
                except Exception as se:
                    print("post-voxel simplify skipped:", se)
                remeshed.merge_vertices()
                trimesh.repair.fix_normals(remeshed)
                m = remeshed
                report["voxel_remeshed"] = True
                report["watertight"] = bool(m.is_watertight)
        except Exception as e:
            print("voxel remesh failed:", repr(e))
            report["voxel_error"] = str(e)
    if return_report:
        return m, report
    return m

def print_check(mesh, target_height_mm=None):
    size = mesh.bounds[1] - mesh.bounds[0]
    if target_height_mm:
        factor = float(target_height_mm) / float(size[2] if size[2] > 0 else 1.0)
        phys = size * factor
    else:
        phys = size
    edges = mesh.edges_unique_length
    if len(edges) > 0:
        min_edge_ratio = float(np.percentile(edges, 5)) / float(size[2] if size[2] > 0 else 1.0)
    else:
        min_edge_ratio = 0.01
    min_feature_mm = min_edge_ratio * (target_height_mm if target_height_mm else max(phys))
    warnings = []
    if max(phys) > MAX_SIZE_MM:
        warnings.append("模型超出最大打印尺寸 200mm，请缩小")
    if min_feature_mm < MIN_FEATURE_MM:
        warnings.append("当前尺寸下细节可能小于 0.5mm 而丢失，建议放大或切换主角模式")
    return {
        "size_mm": [round(float(x), 2) for x in phys],
        "min_feature_mm": round(float(min_feature_mm), 3),
        "printable": len(warnings) == 0,
        "warnings": warnings,
    }

def export_stl(mesh, path):
    mesh.export(path)
    return path
