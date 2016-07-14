# https://sourceforge.net/projects/blenderbitsbobs/
# author: nemyax

import bpy
import bmesh
import os.path
import mathutils as mu
import math
import re

def read_md5mesh(path):
	i = "\s+(\d+)"
	w = "\s+(.+?)"
	a = "(.+?)"
	j_re  = re.compile("\s*\""+a+"\""+w+"\s+\("+w*3+"\s+\)\s+\("+w*3+"\s+\).*")
	v_re  = re.compile("\s*vert"+i+"\s+\("+w*2+"\s+\)"+i*2+".*")
	t_re  = re.compile("\s*tri"+i*4+".*")
	w_re  = re.compile("\s*weight"+i*2+w+"\s+\("+w*3+"\).*")
	e_re  = re.compile("\s*}.*")
	js_re = re.compile("\s*joints\s+{.*")
	n_re  = re.compile("\s*(numverts).*")
	m_re  = re.compile("\s*mesh\s+{.*")
	s_re  = re.compile("\s*shader\s+\""+a+"\".*")
	fh = open(path, "r")
	md5mesh = fh.readlines()
	fh.close()
	ms = do_joints(md5mesh, j_re, e_re)
	pairs = []
	while md5mesh:
		mat_name, bm = do_mesh(md5mesh, s_re, v_re, t_re, w_re, e_re, n_re, ms)
		pairs.append((mat_name, bm))
		skip_until(m_re, md5mesh)
	for mat_name, bm in pairs:
		mesh = bpy.data.meshes.new(os.path.splitext(os.path.basename(path))[0])
		bm.to_mesh(mesh)
		bm.free()
		mesh_o = bpy.data.objects.new(mesh.name, mesh)
		bpy.context.scene.objects.link(mesh_o)
		bpy.context.scene.objects.active = mesh_o
		bpy.ops.object.mode_set(mode='EDIT')
		bpy.ops.object.material_slot_add()
		mat = bpy.data.materials.get(mat_name)
		if not mat:
			mat = bpy.data.materials.new(mat_name)
		mesh_o.material_slots[-1].material = mat
		bpy.ops.object.mode_set()

def do_mesh(md5mesh, s_re, v_re, t_re, w_re, e_re, n_re, ms):
	bm = bmesh.new()
	mat_name = gather(s_re, n_re, md5mesh)[0][0]
	vs, ts, ws = gather_multi([v_re, t_re, w_re], e_re, md5mesh)
	wd	= bm.verts.layers.deform.verify()
	uvs = bm.loops.layers.uv.verify()
	for vi in range(len(vs)):
		wt, nwt = map(int, vs[vi][3:])
		w0 = ws[wt]
		mtx = ms[int(w0[1])][1]
		xyz = mtx * mu.Vector(map(float, w0[3:]))
		new_v = bm.verts.new(xyz)
		bm.verts.index_update()
		for i in ws[wt:wt+nwt]:
			index = int(i[1])
			val = float(i[2])
			new_v[wd][index] = val
	bm.verts.ensure_lookup_table()
	for t in ts:
		tvs = [bm.verts[a] for a in map(int, t[1:])]
		new_f = bm.faces.get(tvs)
		if not new_f:
			new_f = bm.faces.new(tvs)
		bm.faces.index_update()
		for vn in tvs:
			ln = [l for l in new_f.loops if l.vert == vn][0]
			u0, v0 = map(float, vs[vn.index][1:3])
			ln[uvs].uv = (u0, 1.0 - v0)
		new_f.normal_flip()
	return mat_name, bm

def do_joints(md5mesh, j_re, e_re):
	joints = {}
	jdata = gather(j_re, e_re, md5mesh)
	for i in range(len(jdata)):
		joints[i] = jdata[i]
	ms = []
	for j in joints.values():
		j_name = j[0]
		tx, ty, tz, rx, ry, rz = [float(a) for a in j[2:]]
		quat = -mu.Quaternion(restore_quat(rx, ry, rz))
		mtx = mu.Matrix.Translation((tx, ty, tz)) * quat.to_matrix().to_4x4()
		ms.append((j_name, mtx))
	return ms

def gather(regex, end_regex, ls):
	return gather_multi([regex], end_regex, ls)[0]
 
def gather_multi(regexes, end_regex, ls):
	result = [[] for _ in regexes]
	n = len(regexes)
	while ls:
		l = ls.pop(0)
		if end_regex.match(l):
			break
		for i in range(n):
			m = regexes[i].match(l)
			if m:
				result[i].append(m.groups())
				break
	return result

def skip_until(regex, ls):
	while ls:
		if regex.match(ls.pop(0)):
			break

def restore_quat(rx, ry, rz):
	t = 1.0 - (rx * rx) - (ry * ry) - (rz * rz)
	if t < 0.0:
		return (0.0, rx, ry, rz)
	else:
		return (-math.sqrt(t), rx, ry, rz)
