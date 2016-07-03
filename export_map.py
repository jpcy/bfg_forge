# BFG Forge
# Based on Level Buddy by Matt Lucas
# https://matt-lucas.itch.io/level-buddy

#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.	 If not, see <http://www.gnu.org/licenses/>.

import bpy, bmesh, json, math
from . import core
from bpy_extras.io_utils import ExportHelper
from collections import OrderedDict
from mathutils import Euler, Matrix

def ftos(a):
	return ("%f" % a).rstrip('0').rstrip('.')
	
def tuple_to_float_string(t):
	return "%s %s %s" % (ftos(t[0]), ftos(t[1]), ftos(t[2]))
	
def create_primitive(context, obj, obj_transform, index):
	# need a temp mesh to store the result of to_mesh and a temp object for mesh operator
	temp_mesh = obj.to_mesh(context.scene, True, 'PREVIEW')
	temp_mesh.name = "_export_mesh"
	if obj_transform:
		temp_mesh.transform(obj_transform)
	temp_obj = bpy.data.objects.new("_export_obj", temp_mesh)
	context.scene.objects.link(temp_obj)
	temp_obj.select = True
	context.scene.objects.active = temp_obj
	bpy.ops.object.editmode_toggle()
	
	# duplicate verts/0 length edges mess up dmap portal creation
	bm = bmesh.from_edit_mesh(temp_obj.data)
	bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=core._scale_to_blender*0.99) # epsilon < 1 game unit
	bmesh.update_edit_mesh(temp_obj.data)
	bm.free()
	
	bpy.ops.mesh.select_all(action='SELECT')
	#bpy.ops.mesh.vert_connect_concave() # make faces convex
	bpy.ops.mesh.quads_convert_to_tris() # triangulate
	bpy.ops.object.editmode_toggle()
	obj = temp_obj
	mesh = temp_mesh

	# vertex position and normal are decoupled from uvs
	# need to:
	# -create new vertices for each vertex/uv combination
	# -map the old vertex indices to the new ones
	vert_map = list(range(len(mesh.vertices)))
	for i in range(0, len(vert_map)):
		vert_map[i] = list()
	for p in mesh.polygons:
		for i in p.loop_indices:
			loop = mesh.loops[i]
			vert_map[loop.vertex_index].append([0, loop.index])
	num_vertices = 0
	for i, v in enumerate(mesh.vertices):
		for vm in vert_map[i]:
			vm[0] = num_vertices
			num_vertices += 1
			
	prim = OrderedDict()
	prim["primitive"] = index
	
	# vertices	
	verts = prim["verts"] = []		
	for i, v in enumerate(mesh.vertices):
		for vm in vert_map[i]:
			uv = mesh.uv_layers[0].data[vm[1]].uv
			vert = OrderedDict()
			vert["xyz"] = (v.co.x * core._scale_to_game, v.co.y * core._scale_to_game, v.co.z * core._scale_to_game)
			vert["st"] = (uv.x, 1.0 - uv.y)
			vert["normal"] = (v.normal.x, v.normal.y, v.normal.z)
			verts.append(vert)
	
	# polygons
	polygons = prim["polygons"] = []
	for p in mesh.polygons:
		poly = OrderedDict()
		poly["material"] = obj.material_slots[p.material_index].name
		indices = poly["indices"] = []
		for i in p.loop_indices:
			loop = mesh.loops[i]
			v = mesh.vertices[loop.vertex_index]
			uv = mesh.uv_layers[0].data[loop.index].uv
			# find the vert_map nested list element with the matching loop.index
			vm = next(x for x in vert_map[loop.vertex_index] if x[1] == loop.index)
			indices.append(vm[0])
		polygons.append(poly)

	# finished, delete the temp object and mesh
	bpy.ops.object.delete()
	bpy.data.meshes.remove(mesh)
	return prim
	
def export_map(context, filepath, indent):
	# set object mode and clear selection
	if context.active_object:
		bpy.ops.object.mode_set(mode='OBJECT')
	bpy.ops.object.select_all(action='DESELECT')
	
	data = OrderedDict()
	data["version"] = 3
	entities = data["entities"] = []
	entity_index = 0
	
	# write worldspawn
	worldspawn = OrderedDict()
	worldspawn["entity"] = entity_index
	worldspawn["classname"] = "worldspawn"
	primitives = worldspawn["primitives"] = []
	primitive_index = 0
	# write the "build map" output
	built_obj = context.scene.objects.get("_worldspawn")
	if built_obj:
		primitives.append(create_primitive(context, built_obj, built_obj.matrix_world, primitive_index))
		primitive_index += 1
	# write plain mesh objects
	# except for children of brush entities and objects in the "map" group, those are handled elsewhere
	for obj in context.scene.objects:
		if obj.parent and obj.parent.bfg.type == 'BRUSH_ENTITY':
			continue
		map_group = bpy.data.groups.get("map")
		if map_group and obj.name in map_group.objects:
			continue
		if obj.bfg.type == 'NONE' and obj.type == 'MESH':
			primitives.append(create_primitive(context, obj, obj.matrix_world, primitive_index))
			primitive_index += 1
	entities.append(worldspawn)
	entity_index += 1
	
	# write the rest of the entities
	for obj in context.scene.objects:
		if obj.bfg.type in ['BRUSH_ENTITY', 'ENTITY', 'STATIC_MODEL'] or obj.type == 'LAMP':
			ent = OrderedDict()
			ent["entity"] = entity_index
			ent["classname"] = "light" if obj.type == 'LAMP' else obj.bfg.classname
			ent["name"] = obj.name
			ent["origin"] = tuple_to_float_string(obj.location * core._scale_to_game)
			if obj.bfg.type in ['BRUSH_ENTITY','ENTITY']:
				if obj.rotation_euler.z != 0.0:
					ent["angle"] = ftos(math.degrees(obj.rotation_euler.z))
				for prop in obj.game.properties:
					if prop.value != "":
						if prop.name.startswith("inherited_"): # remove the "inherited_" prefix
							ent[prop.name[len("inherited_"):]] = prop.value
						elif prop.name.startswith("custom_"): # remove the "custom_" prefix
							ent[prop.name[len("custom_"):]] = prop.value
						else:
							ent[prop.name] = prop.value
				# brush entity primitives
				if obj.bfg.type == 'BRUSH_ENTITY' and len(obj.children) > 0: # warn if brush entity has no children?
					ent["model"] = obj.name
					primitives = ent["primitives"] = []
					primitive_index = 0
					# find the corresponding "build map" output for this brush entity
					built_obj = context.scene.objects.get("_" + obj.name)
					if built_obj:
						# geometry must be exported in object space
						primitives.append(create_primitive(context, built_obj, Matrix.Translation(-obj.location) * built_obj.matrix_world, primitive_index))
						primitive_index += 1
					# handle plain mesh object children
					for child in obj.children:
						if child.bfg.type == 'NONE' and obj.type == 'MESH':
							# geometry must be exported in object space
							primitives.append(create_primitive(context, child, Matrix.Translation(-obj.location) * child.matrix_world, primitive_index))
							primitive_index += 1
			elif obj.bfg.type == 'STATIC_MODEL':
				ent["model"] = obj.bfg.entity_model.replace("\\", "/")
				angles = obj.rotation_euler
				rot = Euler((-angles[0], -angles[1], -angles[2]), 'XYZ').to_matrix()
				ent["rotation"] = "%s %s %s" % (tuple_to_float_string(rot[0]), tuple_to_float_string(rot[1]), tuple_to_float_string(rot[2]))
			elif obj.type == 'LAMP':
				ent["light_center"] = "0 0 0"
				radius = ftos(obj.data.distance * core._scale_to_game)
				ent["light_radius"] = "%s %s %s" % (radius, radius, radius)
				ent["_color"] = tuple_to_float_string(obj.data.color)
				ent["nospecular"] = "%d" % 0 if obj.data.use_specular else 1
				ent["nodiffuse"] = "%d" % 0 if obj.data.use_diffuse else 1
				if obj.bfg.light_material != "default":
					ent["texture"] = obj.bfg.light_material
			entities.append(ent)
			entity_index += 1
	with open(filepath, 'w') as f:
		json.dump(data, f, indent="\t" if indent else None)

class ExportMap(bpy.types.Operator, ExportHelper):
	bl_idname = "export_scene.rbdoom_map_json"
	bl_label = "Export RBDOOM-3-BFG JSON map"
	bl_options = {'PRESET'}
	filename_ext = ".json"
	indent = bpy.props.BoolProperty(name="Indent", default=False)
		
	def execute(self, context):
		export_map(context, self.filepath, self.indent)
		return {'FINISHED'}
	
def menu_func_export(self, context):
	self.layout.operator(ExportMap.bl_idname, "RBDOOM-3-BFG map (.json)")

def register():
	bpy.types.INFO_MT_file_export.append(menu_func_export)
	
def unregister():
	bpy.types.INFO_MT_file_export.remove(menu_func_export)

if __name__ == "__main__":
	register()
