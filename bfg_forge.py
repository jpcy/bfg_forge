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

bl_info = {
	'name': 'BFG Forge',
	'author': 'Jonathan Young',
	'category': 'Game Engine'
	}
	
import bpy
from bpy_extras.io_utils import ExportHelper
import bpy.utils.previews
import bmesh
import glob
from mathutils import Vector
import os

class Lexer:
	valid_token_chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_/\\-.&:"
	valid_single_tokens = "{}[]()+-*/%!=<>,"

	def __init__(self, filename):
		self.line, self.pos = 1, 0
		with open(filename) as file:
			self.data = file.read()
			
	def eof(self):
		return self.pos >= len(self.data)
		
	def expect_token(self, token):
		t = self.parse_token()
		if not token == t:
			raise Exception("expected token \"%s\", got \"%s\" on line %d" % (token, t, self.line))
		
	def parse_token(self):
		self.skip_whitespace()
		if self.eof():
			return None
		start = self.pos
		while True:
			if self.eof():
				break
			c = self.data[self.pos]
			nc = self.data[self.pos + 1] if self.pos + 1 < len(self.data) else None
			if c == "\"":
				if not start == self.pos:
					raise Exception("quote in middle of token")
				self.pos += 1
				while True:
					if self.eof():
						raise Exception("eof in quoted token")
					c = self.data[self.pos]
					self.pos += 1
					if c == "\"":
						return self.data[start + 1:self.pos - 1]
			elif (c == "/" and nc == "/") or (c == "/" and nc == "*"):
				break
			elif not c in self.valid_token_chars:
				if c in self.valid_single_tokens:
					if self.pos == start:
						# single character token
						self.pos += 1
				break
			self.pos += 1
		end = self.pos
		return self.data[start:end]
		
	def skip_bracket_delimiter_section(self, opening, closing):
		self.expect_token(opening)
		num_required_closing = 1
		while True:
			token = self.parse_token()
			if token == None:
				break
			elif token == opening:
				num_required_closing += 1
			elif token == closing:
				num_required_closing -= 1
				if num_required_closing == 0:
					break
		
	def skip_whitespace(self):
		while True:
			if self.eof():
				break
			c = self.data[self.pos]
			nc = self.data[self.pos + 1] if self.pos + 1 < len(self.data) else None
			if c == "\n":
				self.line += 1
				self.pos += 1
			elif ord(c) <= ord(" "):
				self.pos += 1
			elif c == "/" and nc == "/":
				while True:
					if self.eof() or self.data[self.pos] == "\n":
						break
					self.pos += 1
			elif c == "/" and nc == "*":
				while True:
					if self.eof():
						break
					c = self.data[self.pos]
					nc = self.data[self.pos + 1] if self.pos + 1 < len(self.data) else None
					if c == "*" and nc == "/":
						self.pos += 2
						break
					self.pos += 1
			else:
				break

class FileSystem:
	def __init__(self):
		# highest priority first
		self.search_dirs = []
		if bpy.context.scene.bfg.mod_dir:
			self.search_dirs.append(bpy.context.scene.bfg.mod_dir)
		self.search_dirs.append("basedev")
		self.search_dirs.append("base")
		
	def find_file_path(self, filename):
		for search_dir in self.search_dirs:
			full_path = os.path.join(os.path.realpath(bpy.path.abspath(bpy.context.scene.bfg.game_path)), search_dir, filename)
			if os.path.exists(full_path):
				return full_path
		return None
		
	def for_each_file(self, pattern, callback):
		# don't touch the same file more than once
		# e.g.
		# mymod/materials/base_wall.mtr
		# basedev/materials/base_wall.mtr
		# ignore the second one
		touched_files = []
		for search_dir in self.search_dirs:
			full_path = os.path.join(os.path.realpath(bpy.path.abspath(bpy.context.scene.bfg.game_path)), search_dir)
			if os.path.exists(full_path):
				for f in glob.glob(os.path.join(full_path, pattern)):
					base = os.path.basename(f)
					if not base in touched_files:
						touched_files.append(base)
						callback(full_path, f)
					
class MaterialDeclPathPropGroup(bpy.types.PropertyGroup):
	pass # name property inherited
					
class MaterialDeclPropGroup(bpy.types.PropertyGroup):
	# name property inherited
	diffuse_texture = bpy.props.StringProperty()
	editor_texture = bpy.props.StringProperty()
	heightmap_scale = bpy.props.FloatProperty() # 0 if normal_texture isn't a heightmap
	normal_texture = bpy.props.StringProperty()
	specular_texture = bpy.props.StringProperty()
	
def material_decl_preview_items(self, context):
	materials = []
	pcoll = preview_collections["main"]
	if pcoll.current_decl_path == context.scene.bfg.active_material_decl_path and not pcoll.force_refresh:
		return pcoll.materials
	fs = FileSystem()
	i = 0
	for decl in context.scene.bfg.material_decls:
		if os.path.dirname(decl.name) == context.scene.bfg.active_material_decl_path:
			if context.scene.bfg.hide_bad_materials and (decl.diffuse_texture == "" or not fs.find_file_path(decl.diffuse_texture)):
				continue # hide materials with missing diffuse texture
			basename = os.path.basename(decl.name) # material name without the path
			if basename in pcoll: # workaround blender bug, pcoll.load is supposed to return cached preview if name already exists
				preview = pcoll[basename]
			else:
				preview = None
				if decl.editor_texture != "":
					filename = fs.find_file_path(decl.editor_texture)
					if filename:
						preview = pcoll.load(basename, filename, 'IMAGE')
			materials.append((basename, basename, "", preview.icon_id if preview else 0, i))
			i += 1
	materials.sort()
	pcoll.materials = materials
	pcoll.current_decl_path = context.scene.bfg.active_material_decl_path
	pcoll.force_refresh = False
	return pcoll.materials
					
class ImportMaterials(bpy.types.Operator):
	bl_idname = "scene.import_materials"
	bl_label = "Import Materials"
	
	def __init__(self):
		self.num_materials_created = 0
		self.num_materials_updated = 0
		
	def parse_heightmap(self, decl, lex):
		lex.expect_token("(")
		texture = lex.parse_token()
		lex.expect_token(",")
		scale = float(lex.parse_token())
		lex.expect_token(")")
		return (texture, scale)

	def parse_material_file(self, search_path, filename):
		lex = Lexer(filename)
		num_materials_created = 0
		num_materials_updated = 0
		scene = bpy.context.scene
		print("Parsing", os.path.basename(filename), "...", end="", flush=True)
		while True:
			token = lex.parse_token()
			if token == None:
				break
			if token in [ "particle", "skin", "table"]:
				lex.parse_token() # name
				lex.skip_bracket_delimiter_section("{", "}")
			else:
				if token == "material":
					name = lex.parse_token()
				else:
					name = token
				if name in scene.bfg.material_decls:
					decl = scene.bfg.material_decls[name]
					num_materials_updated += 1
				else:
					num_materials_created += 1
					decl = scene.bfg.material_decls.add()
					decl.name = name
				lex.expect_token("{")
				num_required_closing = 1
				in_stage = False
				stage_blend = None
				stage_heightmap_scale = 0
				stage_texture = None 
				while True:
					token = lex.parse_token()
					if token == None:
						break
					elif token == "{":
						num_required_closing += 1
						if num_required_closing == 2:
							# 2nd opening brace: now in a stage
							in_stage = True
							stage_blend = None
							stage_heightmap_scale = 0
							stage_texture = None
					elif token == "}":
						num_required_closing -= 1
						if num_required_closing == 0:
							break
						elif num_required_closing == 1:
							# one closing brace left: closing stage
							in_stage = False
							if stage_blend and stage_texture:
								if stage_blend.lower() == "bumpmap":
									decl.normal_texture = stage_texture
									decl.heightmap_scale = stage_heightmap_scale
								elif stage_blend.lower() == "diffusemap":
									decl.diffuse_texture = stage_texture
								elif stage_blend.lower() == "specularmap":
									decl.specular_texture = stage_texture
					if in_stage:
						if token.lower() == "blend":
							stage_blend = lex.parse_token()
						elif token.lower() == "map":
							token = lex.parse_token()
							if token.lower() == "heightmap":
								(stage_texture, stage_heightmap_scale) = self.parse_heightmap(decl, lex)
							else:
								stage_texture = token
					else:
						if token.lower() == "bumpmap":
							token = lex.parse_token()
							if token.lower() == "heightmap":
								(decl.normal_texture, decl.heightmap_scale) = self.parse_heightmap(decl, lex)
							else:
								decl.normal_texture = token
						elif token.lower() == "diffusemap":
							decl.diffuse_texture = lex.parse_token()
						elif token.lower() == "qer_editorimage":
							decl.editor_texture = lex.parse_token()
						elif token.lower() == "specularmap":
							decl.specular_texture = lex.parse_token()
		print(" %d materials" % (num_materials_created + num_materials_updated))
		return (num_materials_created, num_materials_updated)
		
	def update_material_decl_paths(self, scene):
		scene.bfg.material_decl_paths.clear()
		for decl in scene.bfg.material_decls:
			name = os.path.dirname(decl.name)
			if not name in scene.bfg.material_decl_paths:
				path = scene.bfg.material_decl_paths.add()
				path.name = name
									
	def execute(self, context):
		if context.scene.bfg.game_path:
			self.num_materials_created = 0
			self.num_materials_updated = 0
		
			def pmf(search_path, filename):
				result = self.parse_material_file(search_path, filename)
				self.num_materials_created += result[0]
				self.num_materials_updated += result[1]

			fs = FileSystem()
			fs.for_each_file(r"materials\*.mtr", pmf)
			self.update_material_decl_paths(context.scene)
			self.report({'INFO'}, "Imported %d materials, updated %d" % (self.num_materials_created, self.num_materials_updated))
		else:
			self.report({'ERROR'}, "RBDOOM-3-BFG path not set")
		return {'FINISHED'}
		
def create_material_texture(fs, mat, texture, slot_number):
	# textures may be shared between materials, so don't create one that already exists
	if texture in bpy.data.textures:
		tex = bpy.data.textures[texture]
	else:
		tex = bpy.data.textures.new(texture, type='IMAGE')
		
	# texture image may have changed
	img_filename = fs.find_file_path(texture)
	if img_filename:
		img_filename = bpy.path.relpath(img_filename) # use relative path for image filenames
	if not tex.image or tex.image.filepath != img_filename:
		try:
			img = bpy.data.images.load(img_filename)
		except:
			pass
		else:
		   tex.image = img	 
	
	# update/create the texture slot
	if not mat.texture_slots[slot_number] or not mat.texture_slots[slot_number].name == texture:
		texSlot = mat.texture_slots.create(slot_number)
		texSlot.texture_coords = 'UV'
		texSlot.texture = tex
	
	return (tex, mat.texture_slots[slot_number])
		
def create_material(decl):
	if decl.name in bpy.data.materials:
		mat = bpy.data.materials[decl.name]
	else:
		mat = bpy.data.materials.new(decl.name)
	mat.use_shadeless = bpy.context.scene.bfg.shadeless_materials
	fs = FileSystem()
	if decl.diffuse_texture != "":
		create_material_texture(fs, mat, decl.diffuse_texture, 0)
	if decl.normal_texture != "":
		(tex, slot) = create_material_texture(fs, mat, decl.normal_texture, 1)
		slot.use_map_color_diffuse = False
		if decl.heightmap_scale > 0:
			slot.use_map_displacement = True
			slot.displacement_factor = decl.heightmap_scale
		else:
			tex.use_normal_map = True
			slot.use_map_normal = True
	if decl.specular_texture != "":
		(_, slot) = create_material_texture(fs, mat, decl.specular_texture, 2)
		slot.use_map_color_diffuse = False
		slot.use_map_color_spec = True
		slot.use_map_specular = True
	return mat
		
def get_active_material(context):
	bfg = context.scene.bfg
	decl_name = bfg.active_material_decl_path + "/" + bfg.active_material_decl
	if not decl_name in context.scene.bfg.material_decls:
		return None
	return create_material(context.scene.bfg.material_decls[decl_name])	
	
class AssignMaterial(bpy.types.Operator):
	bl_idname = "scene.assign_material"
	bl_label = "Assign"
	where = bpy.props.StringProperty(name="where", default='ALL')
	
	def assign(self, obj, mat):
		if obj.bfg.type == 'PLANE':
			if self.where == 'CEILING' or self.where == 'ALL':
				obj.bfg.ceiling_material = mat.name
			if self.where == 'WALL' or self.where == 'ALL':
				obj.bfg.wall_material = mat.name
			if self.where == 'FLOOR' or self.where == 'ALL':
				obj.bfg.floor_material = mat.name
			update_room_plane_materials(obj)
		else:
			if obj.data.materials:
				obj.data.materials[0] = mat
			else:
				obj.data.materials.append(mat)
	
	def execute(self, context):
		obj = context.active_object
		if not obj or not hasattr(obj.data, "materials"):
			return {'FINISHED'}
		if obj.mode == 'EDIT':
			return {'FINISHED'} # TODO: handle assigning to faces
		mat = get_active_material(context)
		if not mat:
			return {'FINISHED'}
		self.assign(obj, mat)
		for s in context.selected_objects:
			self.assign(s, mat)
		return {'FINISHED'}
		
class EntityPropGroup(bpy.types.PropertyGroup):
	# name property inherited
	color = bpy.props.StringProperty()
	usage = bpy.props.StringProperty()
	mins = bpy.props.StringProperty()
	maxs = bpy.props.StringProperty()

class ImportEntities(bpy.types.Operator):
	bl_idname = "scene.import_entities"
	bl_label = "Import Entities"
	
	def parse_def_file(self, scene, search_path, filename):
		lex = Lexer(filename)
		num_entities_created = 0
		num_entities_updated = 0
		print("Parsing", os.path.basename(filename), "...", end="", flush=True)
		while True:
			token = lex.parse_token()
			if token == None:
				break
			if not token == "entityDef":
				lex.parse_token() # name
				lex.skip_bracket_delimiter_section("{", "}")
			else:
				name = lex.parse_token()
				if name in scene.bfg.entities:
					entity = scene.bfg.entities[name]
					num_entities_updated += 1
				else:
					entity = scene.bfg.entities.add()
					entity.name = name
					num_entities_created += 1
				entity.color = "0 0 1" # "r g b"
				entity.mins = ""
				entity.maxs = ""
				entity.usage = ""
				lex.expect_token("{")
				num_required_closing = 1
				while True:
					token = lex.parse_token()
					if token == None:
						break
					elif token == "{":
						num_required_closing += 1
					elif token == "}":
						num_required_closing -= 1
						if num_required_closing == 0:
							break
					elif token == "editor_color":
						entity.color = lex.parse_token()
					elif token == "editor_mins":
						entity.mins = lex.parse_token()
					elif token == "editor_maxs":
						entity.maxs = lex.parse_token()
					elif token == "editor_usage":
						entity.usage = lex.parse_token()
		print(" %d entities" % (num_entities_created + num_entities_updated))
		return (num_entities_created, num_entities_updated)
	
	def execute(self, context):
		if context.scene.bfg.game_path:
			self.num_entities_created = 0
			self.num_entities_updated = 0
		
			def pdf(search_path, filename):
				result = self.parse_def_file(context.scene, search_path, filename)
				self.num_entities_created += result[0]
				self.num_entities_updated += result[1]

			fs = FileSystem()
			fs.for_each_file(r"def\*.def", pdf)
			self.report({'INFO'}, "Imported %d entities, updated %d" % (self.num_entities_created, self.num_entities_updated))
		else:
			self.report({'ERROR'}, "RBDOOM-3-BFG path not set")
		return {'FINISHED'}

def update_wireframe_rooms(self, context):
	for obj in context.scene.objects:
		if obj.bfg.type in ['BRUSH', 'MESH', 'PLANE']:
			obj.draw_type = 'WIRE' if context.scene.bfg.wireframe_rooms else 'TEXTURED'
			
def update_show_entity_names(self, context):
	for obj in context.scene.objects:
		if obj.bfg.type == 'ENTITY':
			obj.show_name = context.scene.bfg.show_entity_names
			
def update_hide_bad_materials(self, context):
	preview_collections["main"].force_refresh = True
	
def update_shadeless_materials(self, context):
	for mat in bpy.data.materials:
		if mat.name != "_object_color":
			mat.use_shadeless = context.scene.bfg.shadeless_materials

def update_room_plane_modifier(obj):
	if obj.modifiers:
		mod = obj.modifiers[0]
		if mod.type == 'SOLIDIFY':
			mod.thickness = obj.bfg.room_height
			mod.material_offset = 1
			mod.material_offset_rim = 2

def update_room_plane_materials(obj):
	if bpy.data.materials.find(obj.bfg.ceiling_material) != -1:
		obj.material_slots[0].material = bpy.data.materials[obj.bfg.ceiling_material]
	if bpy.data.materials.find(obj.bfg.floor_material) != -1:
		obj.material_slots[1].material = bpy.data.materials[obj.bfg.floor_material]
	if bpy.data.materials.find(obj.bfg.wall_material) != -1:
		obj.material_slots[2].material = bpy.data.materials[obj.bfg.wall_material]

def update_room(self, context):
	obj = context.active_object
	if obj.bfg.type == 'PLANE':
		update_room_plane_modifier(obj)
		update_room_plane_materials(obj)

def apply_boolean(dest, src, bool_op):
	bpy.ops.object.select_all(action='DESELECT')
	dest.select = True
	me = src.to_mesh(bpy.context.scene, True, 'PREVIEW')
	ob_bool = bpy.data.objects.new("_bool", me)
	
	# copy transform
	ob_bool.location = src.location
	ob_bool.scale = src.scale
	ob_bool.rotation_euler = src.rotation_euler
	
	# copy materials
	for mat in src.data.materials:
		if not mat.name in dest.data.materials:
			dest.data.materials.append(mat)	
			
	mod = dest.modifiers.new(name=src.name, type='BOOLEAN')
	mod.object = ob_bool
	mod.operation = bool_op
	bpy.ops.object.modifier_apply(apply_as='DATA', modifier=src.name)

def flip_object_normals(obj):
	bpy.ops.object.select_all(action='DESELECT')
	obj.select = True
	bpy.ops.object.editmode_toggle()
	bpy.ops.mesh.select_all(action='SELECT')
	bpy.ops.mesh.flip_normals()
	bpy.ops.object.editmode_toggle()
	
def make_object_faces_convex(obj):
	bpy.ops.object.select_all(action='DESELECT')
	obj.select = True
	bpy.ops.object.editmode_toggle()
	bpy.ops.mesh.select_all(action='SELECT')
	bpy.ops.mesh.vert_connect_concave()
	bpy.ops.object.editmode_toggle()

def auto_texture(obj):
	bpy.ops.object.select_all(action='DESELECT')
	obj.select = True
	bpy.ops.object.editmode_toggle()
	bpy.ops.mesh.select_all(action='SELECT')
	bpy.ops.object.auto_uv_unwrap()
	bpy.ops.object.editmode_toggle()

def move_object_to_layer(obj, layer_number):
	layers = 20 * [False]
	layers[layer_number] = True
	obj.layers = layers

def add_all_materials(obj):
	i = 0
	for m in bpy.data.materials:
		if len(obj.data.materials) > i:
			has_material = False
			for mat in obj.data.materials:
				if mat.name == m.name:
					has_material = True
			if not has_material:
				obj.data.materials[i] = m
		else:
			obj.data.materials.append(m)
		i += 1
		
def link_active_object_to_group(group):
	if not group in bpy.data.groups:
		bpy.ops.group.create(name=group)
	bpy.ops.object.group_link(group=group)

class AddRoom(bpy.types.Operator):
	bl_idname = "scene.add_room"
	bl_label = "Add Room"

	def execute(self, context):
		scene = context.scene
		if context.active_object:
			bpy.ops.object.mode_set(mode='OBJECT')
		bpy.ops.object.select_all(action='DESELECT')
		bpy.ops.mesh.primitive_plane_add(radius=1)
		bpy.ops.object.modifier_add(type='SOLIDIFY')
		obj = context.active_object
		obj.modifiers['Solidify'].offset = 1
		obj.modifiers['Solidify'].use_even_offset = True
		obj.modifiers['Solidify'].use_quality_normals = True
		obj.name = "room"
		obj.data.name = "room"
		obj.bfg.room_height = 4
		obj.bfg.type = 'PLANE'
		if context.scene.bfg.wireframe_rooms:
			obj.draw_type = 'WIRE'
		obj.game.physics_type = 'NO_COLLISION'
		obj.hide_render = True
		if len(bpy.data.materials) > 0:
			mat = get_active_material(context)
			if mat:
				obj.data.materials.append(mat)
				obj.data.materials.append(mat)
				obj.data.materials.append(mat)
				obj.bfg.ceiling_material = mat.name
				obj.bfg.wall_material = mat.name
				obj.bfg.floor_material = mat.name
			else:
				obj.data.materials.append(bpy.data.materials[0])
				obj.data.materials.append(bpy.data.materials[0])
				obj.data.materials.append(bpy.data.materials[0])
				obj.bfg.ceiling_material = bpy.data.materials[0].name
				obj.bfg.wall_material = bpy.data.materials[0].name
				obj.bfg.floor_material = bpy.data.materials[0].name
		else:
			bpy.ops.object.material_slot_add()
			bpy.ops.object.material_slot_add()
			bpy.ops.object.material_slot_add()
			obj.bfg.ceiling_material = ""
			obj.bfg.wall_material = ""
			obj.bfg.floor_material = ""
		scene.objects.active = obj
		update_room_plane_modifier(obj)
		update_room_plane_materials(obj)
		link_active_object_to_group("rooms")
		return {'FINISHED'}

class AddBrush(bpy.types.Operator):
	bl_idname = "scene.add_brush"
	bl_label = "Add Brush"
	s_type = bpy.props.StringProperty(name="s_type", default='BRUSH')

	def execute(self, context):
		scene = context.scene
		if context.active_object:
			bpy.ops.object.mode_set(mode='OBJECT')
		bpy.ops.object.select_all(action='DESELECT')
		bpy.ops.mesh.primitive_cube_add(radius=1)
		obj = context.active_object
		if context.scene.bfg.wireframe_rooms:
			obj.draw_type = 'WIRE'
		obj.name = self.s_type
		obj.data.name = self.s_type
		obj.bfg.type = self.s_type
		mat = get_active_material(context)
		if mat:
			obj.data.materials.append(mat)
		scene.objects.active = obj
		bpy.ops.object.editmode_toggle()
		bpy.ops.mesh.select_all(action='SELECT')
		bpy.ops.object.auto_uv_unwrap()
		bpy.ops.object.editmode_toggle()
		obj.game.physics_type = 'NO_COLLISION'
		obj.hide_render = True
		link_active_object_to_group("brushes")
		return {'FINISHED'}
		
class CopyRoom(bpy.types.Operator):
	bl_idname = "scene.copy_room"
	bl_label = "Copy Room"
	copy_op = bpy.props.StringProperty(name="copy_op", default='ALL')

	def execute(self, context):
		obj = context.active_object
		selected_objects = context.selected_objects
		for s in selected_objects:
			if s.bfg.type == 'PLANE':
				if self.copy_op == 'HEIGHT' or self.copy_op == 'ALL':
					s.bfg.room_height = obj.bfg.room_height
				if self.copy_op == 'MATERIAL_CEILING' or self.copy_op == 'MATERIAL_ALL' or self.copy_op == 'ALL':
					s.bfg.ceiling_material = obj.bfg.ceiling_material
				if self.copy_op == 'MATERIAL_WALL' or self.copy_op == 'MATERIAL_ALL' or self.copy_op == 'ALL':
					s.bfg.wall_material = obj.bfg.wall_material
				if self.copy_op == 'MATERIAL_FLOOR' or self.copy_op == 'MATERIAL_ALL' or self.copy_op == 'ALL':
					s.bfg.floor_material = obj.bfg.floor_material
				update_room_plane_modifier(s)
				update_room_plane_materials(s)
		return {'FINISHED'}

class BuildMap(bpy.types.Operator):
	bl_idname = "scene.build_map"
	bl_label = "Build Map"
	bool_op = bpy.props.StringProperty(name="bool_op", default='INTERSECT')

	def execute(self, context):
		scene = context.scene
		
		# get rooms and brushes
		room_list = []
		brush_list = []
		for obj in context.visible_objects:
			if obj.bfg.type in ['MESH', 'PLANE']:
				room_list.append(obj)
			elif obj.bfg.type == 'BRUSH':
				brush_list.append(obj)
					
		# get all the temp bool objects from the last time the map was built
		bool_objects = [obj for obj in bpy.data.objects if obj.name.startswith("_bool")]
					
		# create map object
		# if a map object already exists, its old mesh is removed
		# if there is at least one room, it is used as the starting point for the map mesh, otherwise an empty mesh is created
		if context.active_object:
			bpy.ops.object.mode_set(mode='OBJECT')
		old_map_mesh = None
		map_name = "_map"
		map_mesh_name = map_name + "_mesh"
		if map_mesh_name in bpy.data.meshes:
			old_map_mesh = bpy.data.meshes[map_mesh_name]
			old_map_mesh.name = "map_old"
		if len(room_list) > 0:
			# first room: generate the mesh and transform to worldspace
			map_mesh = room_list[0].to_mesh(scene, True, 'PREVIEW')
			map_mesh.name = map_mesh_name
			map_mesh.transform(room_list[0].matrix_world)
		else:
			map_mesh = bpy.data.meshes.new(map_mesh_name)
		if map_name in bpy.data.objects:
			map = bpy.data.objects[map_name]
			map.data = map_mesh
		else:
			map = bpy.data.objects.new(map_name, map_mesh)
			scene.objects.link(map)
		if old_map_mesh:
			bpy.data.meshes.remove(old_map_mesh)
		map.layers[scene.active_layer] = True
		scene.objects.active = map
		map.select = True
					
		# combine rooms
		for i, room in enumerate(room_list):
			if i > 0:
				# not the first room: bool union with existing mesh
				apply_boolean(map, room, 'UNION')
		if len(room_list) > 0:
			flip_object_normals(map)
			
		# combine brushes
		for brush in brush_list:
			apply_boolean(map, brush, 'UNION')
			
		auto_texture(map)
		make_object_faces_convex(map)
		link_active_object_to_group("worldspawn")
		move_object_to_layer(map, scene.bfg.map_layer)
		map.hide_select = True
		bpy.ops.object.select_all(action='DESELECT')
		
		# cleanup temp bool objects
		for obj in bool_objects:
			mesh = obj.data
			bpy.data.objects.remove(obj)
			bpy.data.meshes.remove(mesh)

		return {'FINISHED'}

def create_object_color_material():
	name = "_object_color"
	# create the material if it doesn't exist
	if name in bpy.data.materials:
		mat = bpy.data.materials[name]
	else:
		mat = bpy.data.materials.new(name)
	mat.use_fake_user = True
	mat.use_object_color = True
	mat.use_shadeless = True

class AddEntity(bpy.types.Operator):
	bl_idname = "scene.add_entity"
	bl_label = "Add Entity"
	
	def execute(self, context):
		ae = context.scene.bfg.active_entity
		if ae != None and ae != "":
			entity = context.scene.bfg.entities[ae]
			create_object_color_material()
			if context.active_object:
				bpy.ops.object.mode_set(mode='OBJECT')
			bpy.ops.object.select_all(action='DESELECT')
			bpy.ops.mesh.primitive_cube_add()
			obj = context.active_object
			obj.bfg.type = 'ENTITY'
			obj.bfg.classname = ae
			obj.name = ae
			obj.color = [float(i) for i in entity.color.split()] + [float(1)] # "r g b"
			obj.data.name = ae
			obj.data.materials.append(bpy.data.materials["_object_color"])
			obj.lock_rotation = [True, True, False]
			obj.lock_scale = [True, True, True]
			context.scene.objects.active = obj
			link_active_object_to_group("entities")
			context.object.hide_render = True

			# set entity dimensions
			scale = 64.0
			mins = Vector([float(i) * (1.0 / scale) for i in entity.mins.split()])
			maxs = Vector([float(i) * (1.0 / scale) for i in entity.maxs.split()])
			size = maxs + -mins
			obj.dimensions = size
			
			# set entity origin
			origin = (mins + maxs) / 2.0
			bpy.ops.object.editmode_toggle()
			bpy.ops.mesh.select_all(action='SELECT')
			bpy.ops.transform.translate(value=origin)
			bpy.ops.object.editmode_toggle()
		return {'FINISHED'}

class AutoUnwrap(bpy.types.Operator):
	bl_idname = "object.auto_uv_unwrap"
	bl_label = "Unwrap"
	axis = bpy.props.StringProperty(name="Axis", default='AUTO')

	def execute(self, context):
		obj = context.active_object
		me = obj.data
		objectLocation = context.active_object.location
		objectScale = context.active_object.scale
		texelDensity = context.scene.bfg.texel_density
		textureWidth = 64
		textureHeight = 64
		if bpy.context.mode == 'EDIT_MESH' or bpy.context.mode == 'OBJECT':
			was_obj_mode = False
			if bpy.context.mode == 'OBJECT':
				was_obj_mode = True
				bpy.ops.object.editmode_toggle()
				bpy.ops.mesh.select_all(action='SELECT')
			bm = bmesh.from_edit_mesh(me)
			uv_layer = bm.loops.layers.uv.verify()
			bm.faces.layers.tex.verify()  # currently blender needs both layers.
			for f in bm.faces:
				if f.select:
					bpy.ops.uv.select_all(action='SELECT')
					matIndex = f.material_index
					if len(obj.data.materials) > matIndex:
						if obj.data.materials[matIndex] is not None:
							tex = context.active_object.data.materials[matIndex].active_texture
							if tex:
								if hasattr(tex, "image") and tex.image: # if the texture type isn't set to "Image or Movie", the image attribute won't exist
									textureWidth = tex.image.size[0]
									textureHeight = tex.image.size[1]
								nX = f.normal.x
								nY = f.normal.y
								nZ = f.normal.z
								if nX < 0:
									nX = nX * -1
								if nY < 0:
									nY = nY * -1
								if nZ < 0:
									nZ = nZ * -1
								faceNormalLargest = nX
								faceDirection = 'x'
								if faceNormalLargest < nY:
									faceNormalLargest = nY
									faceDirection = 'y'
								if faceNormalLargest < nZ:
									faceNormalLargest = nZ
									faceDirection = 'z'
								if faceDirection == 'x':
									if f.normal.x < 0:
										faceDirection = '-x'
								if faceDirection == 'y':
									if f.normal.y < 0:
										faceDirection = '-y'
								if faceDirection == 'z':
									if f.normal.z < 0:
										faceDirection = '-z'
								if self.axis == 'X':
									faceDirection = 'x'
								if self.axis == 'Y':
									faceDirection = 'y'
								if self.axis == 'Z':
									faceDirection = 'z'
								if self.axis == '-X':
									faceDirection = '-x'
								if self.axis == '-Y':
									faceDirection = '-y'
								if self.axis == '-Z':
									faceDirection = '-z'
								for l in f.loops:
									luv = l[uv_layer]
									if luv.select and l[uv_layer].pin_uv is not True:
										if faceDirection == 'x':
											luv.uv.x = ((l.vert.co.y * objectScale[1]) + objectLocation[1]) * texelDensity / textureWidth
											luv.uv.y = ((l.vert.co.z * objectScale[2]) + objectLocation[2]) * texelDensity / textureWidth
										if faceDirection == '-x':
											luv.uv.x = (((l.vert.co.y * objectScale[1]) + objectLocation[1]) * texelDensity / textureWidth) * -1
											luv.uv.y = ((l.vert.co.z * objectScale[2]) + objectLocation[2]) * texelDensity / textureWidth
										if faceDirection == 'y':
											luv.uv.x = (((l.vert.co.x * objectScale[0]) + objectLocation[0]) * texelDensity / textureWidth) * -1
											luv.uv.y = ((l.vert.co.z * objectScale[2]) + objectLocation[2]) * texelDensity / textureWidth
										if faceDirection == '-y':
											luv.uv.x = ((l.vert.co.x * objectScale[0]) + objectLocation[0]) * texelDensity / textureWidth
											luv.uv.y = ((l.vert.co.z * objectScale[2]) + objectLocation[2]) * texelDensity / textureWidth
										if faceDirection == 'z':
											luv.uv.x = ((l.vert.co.x * objectScale[0]) + objectLocation[0]) * texelDensity / textureWidth
											luv.uv.y = ((l.vert.co.y * objectScale[1]) + objectLocation[1]) * texelDensity / textureWidth
										if faceDirection == '-z':
											luv.uv.x = (((l.vert.co.x * objectScale[0]) + objectLocation[0]) * texelDensity / textureWidth) * 1
											luv.uv.y = (((l.vert.co.y * objectScale[1]) + objectLocation[1]) * texelDensity / textureWidth) * -1
										luv.uv.x = luv.uv.x - context.scene.bfg.offset_x
										luv.uv.y = luv.uv.y - context.scene.bfg.offset_y
			bmesh.update_edit_mesh(me)
			if was_obj_mode:
				bpy.ops.object.editmode_toggle()
		return {'FINISHED'}

class PinUV(bpy.types.Operator):
	bl_idname = "object.auto_uv_pin"
	bl_label = "Pin UV"
	p = bpy.props.BoolProperty(name="tp", default=True)

	def execute(self, context):
		obj = bpy.context.object
		if obj.mode == 'EDIT':
			me = obj.data
			bm = bmesh.from_edit_mesh(me)
			uv_layer = bm.loops.layers.uv.verify()
			bm.faces.layers.tex.verify()
			bpy.ops.uv.pin(clear=self.p)
			bmesh.update_edit_mesh(me)
		return {'FINISHED'}

class NudgeUV(bpy.types.Operator):
	bl_idname = "object.auto_uv_nudge"
	bl_label = "Nudge UV"
	dir = bpy.props.StringProperty(name="Some Floating Point", default='LEFT')

	def execute(self, context):
		obj = context.active_object
		me = obj.data
		bm = bmesh.from_edit_mesh(me)
		uv_layer = bm.loops.layers.uv.verify()
		bm.faces.layers.tex.verify()  # currently blender needs both layers.

		# adjust UVs on all selected faces
		for f in bm.faces:
			# is this face currently selected?
			if f.select:
				# make sure that all the uvs for the face are selected
				bpy.ops.uv.select_all(action='SELECT')
				# loop through the face uvs
				for l in f.loops:
					luv = l[uv_layer]
					# only work on the selected UV layer
					if luv.select:
						if self.dir == 'LEFT':
							luv.uv.x = luv.uv.x + context.scene.bfg.nudge_amount
						if self.dir == 'RIGHT':
							luv.uv.x = luv.uv.x - context.scene.bfg.nudge_amount
						if self.dir == 'UP':
							luv.uv.y = luv.uv.y - context.scene.bfg.nudge_amount
						if self.dir == 'DOWN':
							luv.uv.y = luv.uv.y + context.scene.bfg.nudge_amount
						if self.dir == 'HORIZONTAL':
							luv.uv.x = luv.uv.x * -1
						if self.dir == 'VERTICAL':
							luv.uv.y = luv.uv.y * -1
		# update the mesh
		bmesh.update_edit_mesh(me)
		return {'FINISHED'}
		
class SettingsPanel(bpy.types.Panel):
	bl_label = "Settings"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"

	def draw(self, context):
		scene = context.scene
		box = self.layout.box()
		col = box.column()
		col.label("RBDOOM-3-BFG Path", icon='LOGIC')
		col.prop(scene.bfg, "game_path", "Path")
		col.prop(scene.bfg, "mod_dir")
		col = self.layout.column()
		col.operator(ImportMaterials.bl_idname, ImportMaterials.bl_label, icon='MATERIAL')
		col.operator(ImportEntities.bl_idname, ImportEntities.bl_label, icon='POSE_HLT')
		col.prop(scene.bfg, "wireframe_rooms")
		col.prop(scene.bfg, "show_entity_names")
		col.prop(scene.bfg, "hide_bad_materials")
		col.prop(scene.bfg, "shadeless_materials")
		
class CreatePanel(bpy.types.Panel):
	bl_label = "Create"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"
	
	def draw(self, context):
		scene = context.scene
		col = self.layout.column(align=True)
		col.operator(AddRoom.bl_idname, "Add 2D Room", icon='SURFACE_NCURVE')
		col.operator(AddBrush.bl_idname, "Add 3D Room", icon='SNAP_FACE').s_type = 'MESH'
		col.operator(AddBrush.bl_idname, "Add Brush", icon='SNAP_VOLUME').s_type = 'BRUSH'
		if len(scene.bfg.entities) > 0:
			box = self.layout.box()
			col = box.column()
			col.prop_search(scene.bfg, "active_entity", scene.bfg, "entities", "", icon='SCRIPT')
			ae = scene.bfg.active_entity
			if ae != None and ae != "":
				usage = scene.bfg.entities[ae].usage
				if usage:
					col.label(usage)
				col.operator(AddEntity.bl_idname, AddEntity.bl_label, icon='POSE_HLT')
		
class MapPanel(bpy.types.Panel):
	bl_label = "Map"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"

	def draw(self, context):
		col = self.layout.column(align=True)
		col.operator(BuildMap.bl_idname, "Build Map", icon='MOD_BUILD').bool_op = 'UNION'
		col.prop(context.scene.bfg, "map_layer")
		
class MaterialPanel(bpy.types.Panel):
	bl_label = "Material"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"
	
	def draw(self, context):
		scene = context.scene
		if len(scene.bfg.material_decls) > 0:
			col = self.layout.column()
			col.prop_search(scene.bfg, "active_material_decl_path", scene.bfg, "material_decl_paths", "", icon='MATERIAL_DATA')
			col.template_icon_view(scene.bfg, "active_material_decl")
			col.prop(scene.bfg, "active_material_decl", "")
			if context.active_object and len(context.selected_objects) > 0 and hasattr(context.active_object.data, "materials"):
				if context.active_object.bfg.type == 'PLANE':
					col.label("Assign:", icon='MATERIAL_DATA')
					row = col.row(align=True)
					row.operator(AssignMaterial.bl_idname, "Ceiling").where = 'CEILING'
					row.operator(AssignMaterial.bl_idname, "Wall").where = 'WALL'
					row.operator(AssignMaterial.bl_idname, "Floor").where = 'FLOOR'
					row.operator(AssignMaterial.bl_idname, "All").where = 'ALL'
				else:
					col.operator(AssignMaterial.bl_idname, AssignMaterial.bl_label, icon='MATERIAL_DATA')

class ObjectPanel(bpy.types.Panel):
	bl_label = "Object"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"

	def draw(self, context):
		obj = context.active_object
		if obj and len(context.selected_objects) > 0:
			col = self.layout.column(align=True)
			col.label(obj.name, icon='OBJECT_DATAMODE')
			if obj.bfg.type == 'PLANE' and obj.modifiers:
				mod = obj.modifiers[0]
				if mod.type == 'SOLIDIFY':
					col.separator()
					col.prop(obj.bfg, "room_height")
					col.operator(CopyRoom.bl_idname, "Copy Room Height", icon='PASTEFLIPUP').copy_op = 'HEIGHT'
					col.separator()
					sub = col.column()
					sub.enabled = False
					sub.prop(obj.bfg, "ceiling_material", "Ceiling")
					sub.prop(obj.bfg, "wall_material", "Wall")
					sub.prop(obj.bfg, "floor_material", "Floor")
					col.separator()
					col.label("Copy Materials:", icon='PASTEFLIPUP')
					row = col.row(align=True)
					row.operator(CopyRoom.bl_idname, "Ceiling").copy_op = 'MATERIAL_CEILING'
					row.operator(CopyRoom.bl_idname, "Wall").copy_op = 'MATERIAL_WALL'
					row.operator(CopyRoom.bl_idname, "Floor").copy_op = 'MATERIAL_FLOOR'
					row.operator(CopyRoom.bl_idname, "All").copy_op = 'MATERIAL_ALL'

class UvPanel(bpy.types.Panel):
	bl_label = "UV"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"

	def draw(self, context):
		layout = self.layout
		col = layout.column(align=True)
		col.label("Texel Density", icon='LATTICE_DATA')
		col.prop(context.scene.bfg, "texel_density", "")
		if context.mode == 'EDIT_MESH' or context.mode == 'OBJECT':
			col = layout.column(align=True)
			col.label("Mapping", icon='FACESEL_HLT')
			row = layout.row(align=True)
			row.operator(AutoUnwrap.bl_idname, "Auto").axis = 'AUTO'
			row = layout.row(align=True)
			row.operator(AutoUnwrap.bl_idname, "X").axis = 'X'
			row.operator(AutoUnwrap.bl_idname, "Y").axis = 'Y'
			row.operator(AutoUnwrap.bl_idname, "Z").axis = 'Z'
			row = layout.row(align=True)
			row.operator(AutoUnwrap.bl_idname, "-X").axis = '-X'
			row.operator(AutoUnwrap.bl_idname, "-Y").axis = '-Y'
			row.operator(AutoUnwrap.bl_idname, "-Z").axis = '-Z'
			if context.mode == 'EDIT_MESH':
				row = layout.row(align=True)
				row.operator(PinUV.bl_idname, "Pin UVs").p = False
				row.operator(PinUV.bl_idname, "Un-Pin UVs").p = True
				col = layout.column(align=True)
				col.label("Offset", icon='FULLSCREEN_ENTER')
				row = layout.row(align=True)
				row.prop(context.scene.bfg, "offset_x", 'X')
				row.prop(context.scene.bfg, "offset_y", 'Y')
				col = layout.column(align=True)
				col.label("Nudge UVs", icon='FORWARD')
				row = layout.row(align=True)
				row.operator(NudgeUV.bl_idname, "Left").dir = 'LEFT'
				row.operator(NudgeUV.bl_idname, "Right").dir = 'RIGHT'
				row = layout.row(align=True)
				row.operator(NudgeUV.bl_idname, "Up").dir = 'UP'
				row.operator(NudgeUV.bl_idname, "Down").dir = 'DOWN'
				row = layout.row(align=True)
				row.prop(context.scene.bfg, "nudge_amount", "Amount")
				col = layout.column(align=True)
				col.label("Flip", icon='LOOP_BACK')
				row = layout.row(align=True)
				row.operator(NudgeUV.bl_idname, "Horizontal").dir = 'HORIZONTAL'
				row.operator(NudgeUV.bl_idname, "Vertical").dir = 'VERTICAL'
				
def ftos(a):
	return ("%f" % a).rstrip('0').rstrip('.')
		
class ExportMap(bpy.types.Operator, ExportHelper):
	bl_idname = "export_scene.map"
	bl_label = "Export RBDOOM-3-BFG map"
	bl_options = {'PRESET'}
	filename_ext = ".map"
	scale = bpy.props.FloatProperty(name="Scale", default=64, min=1, max=1024)
	
	def write_entity(self, f, entity):
		f.write("{\n")
		f.write("\"classname\" \"%s\"\n" % entity.bfg.classname)
		f.write("\"name\" \"%s\"\n" % entity.name)
		f.write("\"origin\" \"%s %s %s\"\n" % (ftos(entity.location[0] * self.scale), ftos(entity.location[1] * self.scale), ftos(entity.location[2] * self.scale)))
		f.write("}\n")
	
	def write_mesh(self, f, object, mesh):
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
		
		# header
		f.write(" meshDef\n")
		f.write(" {\n")
		f.write("  ( %d %d 0 0 0 )\n" % (num_vertices, len(mesh.polygons)))

		# vertices				
		f.write("  (\n")
		for i, v in enumerate(mesh.vertices):
			for vm in vert_map[i]:
				uv = mesh.uv_layers[0].data[vm[1]].uv
				f.write("   ( %s %s %s %s %s %s %s %s )\n" % (ftos(v.co.x * self.scale), ftos(v.co.y * self.scale), ftos(v.co.z * self.scale), ftos(uv.x), ftos(uv.y), ftos(v.normal.x), ftos(v.normal.y), ftos(v.normal.z)))
		f.write("  )\n")
		
		# faces
		f.write("  (\n")
		for p in mesh.polygons:
			f.write("   \"%s\" %d = " % (object.material_slots[p.material_index].name, p.loop_total))
			for i in reversed(p.loop_indices):
				loop = mesh.loops[i]
				v = mesh.vertices[loop.vertex_index]
				uv = mesh.uv_layers[0].data[loop.index].uv
				# find the vert_map nested list element with the matching loop.index
				vm = next(x for x in vert_map[loop.vertex_index] if x[1] == loop.index)
				f.write("%d " % vm[0])
			f.write("\n")
		f.write("  )\n")
		
		# footer
		f.write(" }\n")
		
	def execute(self, context):
		if not "_map" in bpy.data.objects:
			self.report({'ERROR'}, "Build the map first")
		else:
			map = bpy.data.objects["_map"]
			f = open(self.filepath, 'w')
			f.write("Version 3\n")
			
			# entity 0
			f.write("{\n")
			f.write("\"classname\" \"worldspawn\"\n")
			
			# primitives
			f.write("{\n")
			self.write_mesh(f, map, map.data)
			f.write("}\n")
			
			f.write("}\n")
			
			# entity 1
			for obj in context.scene.objects:
				if obj.bfg.type == 'ENTITY':
					self.write_entity(f, obj)
							
			f.close()
		return {'FINISHED'}
	
def menu_func_export(self, context):
	self.layout.operator(ExportMap.bl_idname, "RBDOOM-3-BFG map (.map)")
	
class BfgScenePropertyGroup(bpy.types.PropertyGroup):
	game_path = bpy.props.StringProperty(name="RBDOOM-3-BFG Path", subtype='DIR_PATH')
	mod_dir = bpy.props.StringProperty(name="Mod Directory")
	wireframe_rooms = bpy.props.BoolProperty(name="Wireframe rooms", default=True, update=update_wireframe_rooms)
	show_entity_names = bpy.props.BoolProperty(name="Show entity names", default=False, update=update_show_entity_names)
	hide_bad_materials = bpy.props.BoolProperty(name="Hide bad materials", description="Hide materials with missing diffuse textures", default=True, update=update_hide_bad_materials)
	shadeless_materials = bpy.props.BoolProperty(name="Fullbright materials", description="Disable lighting on materials", default=True, update=update_shadeless_materials)
	map_layer = bpy.props.IntProperty(name="Layer", default=0, min=0, max=19)
	material_decl_paths = bpy.props.CollectionProperty(type=MaterialDeclPathPropGroup)
	active_material_decl_path = bpy.props.StringProperty(name="", default="")
	material_decls = bpy.props.CollectionProperty(type=MaterialDeclPropGroup)
	active_material_decl = bpy.props.EnumProperty(name="", items=material_decl_preview_items)
	entities = bpy.props.CollectionProperty(type=EntityPropGroup)
	active_entity = bpy.props.StringProperty(name="Active Entity", default="")
	texel_density = bpy.props.IntProperty(name="Texel Density", default=128, step=128, min=8, max=512)
	offset_x = bpy.props.FloatProperty(name="Offset X", default=0)
	offset_y = bpy.props.FloatProperty(name="Offset Y", default=0)
	nudge_amount = bpy.props.FloatProperty(name="Nudge Amount", default=0.125)
	
class BfgObjectPropertyGroup(bpy.types.PropertyGroup):
	classname = bpy.props.StringProperty(name="Classname", default="")
	room_height = bpy.props.FloatProperty(name="Room Height", default=4, step=20, precision=1, update=update_room)
	floor_material = bpy.props.StringProperty(name="Floor Material", update=update_room)
	wall_material = bpy.props.StringProperty(name="Wall Material", update=update_room)
	ceiling_material = bpy.props.StringProperty(name="Ceiling Material", update=update_room)
	type = bpy.props.EnumProperty(items=[
		('ENTITY', "Entity", ""),
		('BRUSH', "Brush", ""),
		('MESH', "3D Room", ""),
		('PLANE', "2D Room", ""),
		('NONE', "None", "")
	], name="BFG Forge Object Type", default='NONE')
	
preview_collections = {}
	
def register():
	bpy.utils.register_module(__name__)
	bpy.types.INFO_MT_file_export.append(menu_func_export)
	bpy.types.Scene.bfg = bpy.props.PointerProperty(type=BfgScenePropertyGroup)
	bpy.types.Object.bfg = bpy.props.PointerProperty(type=BfgObjectPropertyGroup)
	pcoll = bpy.utils.previews.new()
	pcoll.materials = ()
	pcoll.current_decl_path = ""
	pcoll.force_refresh = False
	preview_collections["main"] = pcoll

def unregister():
	bpy.utils.unregister_module(__name__)
	bpy.types.INFO_MT_file_export.remove(menu_func_export)
	del bpy.types.Scene.bfg
	del bpy.types.Object.bfg
	for pcoll in preview_collections.values():
		bpy.utils.previews.remove(pcoll)
	preview_collections.clear()

if __name__ == "__main__":
	register()
	
	'''
	lex = Lexer(r"")
	while True:
		last_pos = lex.pos
		token = lex.parse_token()
		if token == None:
			break
		if lex.pos == last_pos:
			raise Exception("hang detected")
			break
		print(token)
	'''
