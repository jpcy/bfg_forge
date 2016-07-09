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
	
import bpy, bpy.utils.previews, bmesh, glob, math, os, time
from . import lexer
from mathutils import Vector

# used when creating light and entities, and exporting
_scale_to_game = 64.0
_scale_to_blender = 1.0 / _scale_to_game

_editor_material_paths = ["textures/common", "textures/editor"]

preview_collections = {}
				
################################################################################
## FILE SYSTEM
################################################################################

class FileSystem:
	def __init__(self):
		# highest priority first
		self.search_dirs = []
		if bpy.context.scene.bfg.mod_dir:
			self.search_dirs.append(bpy.context.scene.bfg.mod_dir)
		self.search_dirs.append("basedev")
		self.search_dirs.append("base")
		
	def calculate_relative_path(self, filename):
		# e.g. if game_path is "D:\Games\DOOM 3",
		# "D:\Games\DOOM 3\basedev\models\mapobjects\arcade_machine\arcade_machine.lwo"
		# should return
		# "models\mapobjects\arcade_machine\arcade_machine.lwo"
		for search_dir in self.search_dirs:
			full_search_path = os.path.join(os.path.realpath(bpy.path.abspath(bpy.context.scene.bfg.game_path)), search_dir).lower()
			full_file_path = os.path.realpath(bpy.path.abspath(filename)).lower()
			if full_file_path.startswith(full_search_path):
				return os.path.relpath(full_file_path, full_search_path)
		return None
		
	def find_file_path(self, filename):
		for search_dir in self.search_dirs:
			full_path = os.path.join(os.path.realpath(bpy.path.abspath(bpy.context.scene.bfg.game_path)), search_dir, filename)
			if os.path.exists(full_path):
				return full_path
		return None
		
	def find_image_file_path(self, filename):
		if filename == "_black":
			filename = "textures/black"
		elif filename == "_white":
			filename = "guis/assets/white"
		path = self.find_file_path(filename)
		if not path:
			split = os.path.splitext(filename)
			if split[1] == "":
				# no extension, try tga
				path = self.find_file_path(split[0] + ".tga")
				if not path:
					# no tga, try png
					path = self.find_file_path(split[0] + ".png")
		return path
		
	def find_files(self, pattern):
		# don't touch the same file more than once
		# e.g.
		# mymod/materials/base_wall.mtr
		# basedev/materials/base_wall.mtr
		# ignore the second one
		touched_files = []
		found_files = []
		for search_dir in self.search_dirs:
			full_path = os.path.join(os.path.realpath(bpy.path.abspath(bpy.context.scene.bfg.game_path)), search_dir)
			if os.path.exists(full_path):
				for f in glob.glob(os.path.join(full_path, pattern)):
					base = os.path.basename(f)
					if not base in touched_files:
						touched_files.append(base)
						found_files.append(f)
		return found_files
						
################################################################################
## UTILITY FUNCTIONS
################################################################################

def min_nullable(a, b):
	if a == None or b < a:
		return b
	return a
	
def max_nullable(a, b):
	if a == None or b > a:
		return b
	return a
	
def set_object_mode_and_clear_selection():
	if bpy.context.active_object:
		bpy.ops.object.mode_set(mode='OBJECT')
	bpy.ops.object.select_all(action='DESELECT')
	
def link_active_object_to_group(group):
	if not group in bpy.data.groups:
		bpy.ops.group.create(name=group)
	bpy.ops.object.group_link(group=group)
						
################################################################################
## MATERIALS
################################################################################
					
class MaterialDeclPathPropGroup(bpy.types.PropertyGroup):
	pass # name property inherited
					
class MaterialDeclPropGroup(bpy.types.PropertyGroup):
	# name property inherited
	diffuse_texture = bpy.props.StringProperty()
	editor_texture = bpy.props.StringProperty()
	heightmap_scale = bpy.props.FloatProperty() # 0 if normal_texture isn't a heightmap
	normal_texture = bpy.props.StringProperty()
	specular_texture = bpy.props.StringProperty()
	texture = bpy.props.StringProperty() # any stage texture map. will be the light texture for light materials.
	
def material_decl_preview_items(self, context):
	materials = []
	pcoll = preview_collections["material"]
	if pcoll.current_decl_path == context.scene.bfg.active_material_decl_path and not pcoll.force_refresh:
		return pcoll.materials
	fs = FileSystem()
	i = 0
	for decl in context.scene.bfg.material_decls:
		decl_path = os.path.dirname(decl.name)
		if decl_path == context.scene.bfg.active_material_decl_path:
			if context.scene.bfg.hide_bad_materials and decl_path not in _editor_material_paths and (decl.diffuse_texture == "" or not fs.find_image_file_path(decl.diffuse_texture)):
				# hide materials with missing diffuse texture, but not editor materials
				continue
			if decl.editor_texture in pcoll: # workaround blender bug, pcoll.load is supposed to return cached preview if name already exists
				preview = pcoll[decl.editor_texture]
			else:
				preview = None
				if decl.editor_texture != "":
					filename = fs.find_image_file_path(decl.editor_texture)
					if filename:
						preview = pcoll.load(decl.editor_texture, filename, 'IMAGE')
			materials.append((decl.name, os.path.basename(decl.name), decl.name, preview.icon_id if preview else 0, i))
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
		
	def parse_addnormals(self, decl, lex):
		lex.expect_token("(")
		return lex.parse_token()
		
	def parse_heightmap(self, decl, lex):
		lex.expect_token("(")
		texture = lex.parse_token()
		lex.expect_token(",")
		scale = float(lex.parse_token())
		lex.expect_token(")")
		return (texture, scale)

	def parse_material_file(self, filename):
		lex = lexer.Lexer(filename)
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
							if stage_texture:
								decl.texture = stage_texture # any stage texture map. will be the light texture for light materials.
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
							if token.lower() == "addnormals":
								stage_texture = self.parse_addnormals(decl, lex)
							elif token.lower() == "heightmap":
								(stage_texture, stage_heightmap_scale) = self.parse_heightmap(decl, lex)
							else:
								stage_texture = token
					else:
						if token.lower() == "bumpmap":
							token = lex.parse_token()
							if token.lower() == "addnormals":
								decl.normal_texture = self.parse_addnormals(decl, lex)
							elif token.lower() == "heightmap":
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
			if name.startswith("textures") and not name in scene.bfg.material_decl_paths:
				path = scene.bfg.material_decl_paths.add()
				path.name = name
				
	@classmethod
	def poll(cls, context):
		return context.scene.bfg.game_path != ""
									
	def execute(self, context):
		self.num_materials_created = 0
		self.num_materials_updated = 0
		start_time = time.time() 
		fs = FileSystem()
		files = fs.find_files(os.path.join("materials", "*.mtr"))
		wm = context.window_manager
		wm.progress_begin(0, len(files))
		for i, f in enumerate(files):
			result = self.parse_material_file(f)
			wm.progress_update(i)
			self.num_materials_created += result[0]
			self.num_materials_updated += result[1]
		self.update_material_decl_paths(context.scene)
		preview_collections["light"].needs_refresh = True
		wm.progress_end()
		self.report({'INFO'}, "Imported %d materials, updated %d in %.2f seconds" % (self.num_materials_created, self.num_materials_updated, time.time() - start_time))
		return {'FINISHED'}
		
def create_material_texture(fs, mat, texture, slot_number):
	# textures may be shared between materials, so don't create one that already exists
	if texture in bpy.data.textures:
		tex = bpy.data.textures[texture]
	else:
		tex = bpy.data.textures.new(texture, type='IMAGE')
		
	# texture image may have changed
	img_filename = fs.find_image_file_path(texture)
	if img_filename:
		# try to use relative paths for image filenames
		try:
			img_filename = bpy.path.relpath(img_filename)
		except ValueError:
			pass
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
	fs = FileSystem()
	decl_path = os.path.dirname(decl.name)
	mat.preview_render_type = 'CUBE'
	if decl_path in _editor_material_paths:
		# editor materials: use the editor texture if diffuse is missing
		create_material_texture(fs, mat, decl.diffuse_texture if decl.diffuse_texture != "" else decl.editor_texture, 0)
		mat.alpha = 0.5
		mat.transparency_method = 'Z_TRANSPARENCY'
		mat.use_shadeless = True
		mat.use_transparency = True
	else:
		mat.use_shadeless = bpy.context.scene.bfg.shadeless_materials
		if decl.diffuse_texture != "":
			create_material_texture(fs, mat, decl.diffuse_texture, 0)
		elif decl.texture != "": # fallback to generic texture if no diffuse
			create_material_texture(fs, mat, decl.texture, 0)
		elif decl.editor_texture != "": # fallback to editor texture if no diffuse or generic
			create_material_texture(fs, mat, decl.editor_texture, 0)	
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
	
def get_or_create_active_material(context):
	bfg = context.scene.bfg
	if bfg.active_material_decl in context.scene.bfg.material_decls:
		return create_material(context.scene.bfg.material_decls[bfg.active_material_decl])
	return None
	
def assign_material(obj, mat, where='ALL'):
	if obj.bfg.type == '2D_ROOM':
		if where == 'CEILING' or where == 'ALL':
			obj.bfg.ceiling_material = mat.name
		if where == 'WALL' or where == 'ALL':
			obj.bfg.wall_material = mat.name
		if where == 'FLOOR' or where == 'ALL':
			obj.bfg.floor_material = mat.name
		update_room_plane_materials(obj)
	else:
		if len(obj.data.materials) == 1:
			# one slot: easy, just reassign
			obj.data.materials[0] = mat
		else:
			obj.data.materials.clear()
			obj.data.materials.append(mat)
			
			# there was more than one material slot on this object
			# need to set material_index on all faces to 0
			bm = bmesh.new()
			bm.from_mesh(obj.data)
			for f in bm.faces:
				f.material_index = 0
			bm.to_mesh(obj.data)
			bm.free()
			
class AssignMaterial(bpy.types.Operator):
	"""Assign the material to the selected objects or object faces"""
	bl_idname = "scene.assign_material"
	bl_label = "Assign"
	where = bpy.props.StringProperty(name="where", default='ALL')
	
	def execute(self, context):
		obj = context.active_object
		if not obj:
			return {'CANCELLED'}
		mat = get_or_create_active_material(context)
		if not mat:
			return {'CANCELLED'}
		if obj.mode == 'EDIT' and hasattr(obj.data, "materials"):
			# edit mode: assign to selected mesh faces
			bm = bmesh.from_edit_mesh(obj.data)
			selected_faces = [f for f in bm.faces if f.select]
			if len(selected_faces) > 0:
				# create/find a slot
				material_index = -1
				for i, m in enumerate(obj.data.materials):
					if m == mat:
						material_index = i
						break
				if material_index == -1:
					obj.data.materials.append(mat)
					material_index = len(obj.data.materials) - 1
					
				# assign to faces
				for f in selected_faces:
					f.material_index = material_index
					
				# remove any material slots that are now unused
				# pop function update_data arg doesn't work, need to remap face material_index ourselves after removal
				old_material_names = []
				for m in obj.data.materials:
					old_material_names.append(m.name)
				remove_materials = []
				for i, m in enumerate(obj.data.materials):
					used = False
					for f in bm.faces:
						if f.material_index == i:
							used = True
							break
					if not used:
						remove_materials.append(m)
				if len(remove_materials) > 0:
					for m in remove_materials:
						obj.data.materials.pop(obj.data.materials.find(m.name), True)
				for f in bm.faces:
					f.material_index = obj.data.materials.find(old_material_names[f.material_index])
					
				bmesh.update_edit_mesh(obj.data)
			#bm.free() # bmesh.from_edit_mesh returns garbage after this is called
		else:
			for s in context.selected_objects:
				if hasattr(s.data, "materials"):
					assign_material(s, mat, self.where)
		return {'FINISHED'}
		
def refresh_selected_objects_materials(context):
	refreshed = [] # don't refresh the same material twice
	for obj in context.selected_objects:
		if hasattr(obj.data, "materials"):
			for mat in obj.data.materials:
				if mat not in refreshed and mat.name in context.scene.bfg.material_decls:
					decl = context.scene.bfg.material_decls[mat.name]
					create_material(decl)
					refreshed.append(mat)
		
class RefreshMaterials(bpy.types.Operator):
	"""Refresh the select objects' materials, recreating them from their corresponding material decls"""
	bl_idname = "scene.refresh_materials"
	bl_label = "Refresh Materials"
	
	@classmethod
	def poll(cls, context):
		return len(context.scene.bfg.material_decls) > 0
	
	def execute(self, context):
		refresh_selected_objects_materials(context)
		return {'FINISHED'}
		
################################################################################
## MODELS
################################################################################

# creates a new object with the specified model either loaded into a new mesh, or linked to an existing mesh
# the object will be made active and selected
# return (object, error_message)
def create_model_object(context, filename, relative_path):
	# check that the required import addon is enabled
	extension = os.path.splitext(filename)[1]
	if extension.lower() == ".lwo":
		if not hasattr(bpy.types, "IMPORT_SCENE_OT_lwo"):
			return (None, "LightWave Object (.lwo) import addon not enabled")
	elif extension.lower() not in [".dae"]:
		return (None, "Model \"%s\" uses unsupported extension \"%s\"" % (filename, extension))
	
	set_object_mode_and_clear_selection()
	
	# if the model has already been loaded before, don't import - link to the existing mesh
	mesh = None
	for obj in context.scene.objects:
		if obj.bfg.entity_model == relative_path:
			mesh = obj.data
			break
	if mesh:
		obj = bpy.data.objects.new(os.path.splitext(os.path.basename(relative_path))[0], mesh)
		context.scene.objects.link(obj)
	else:
		obj = None
		if extension.lower() == ".dae":
			bpy.ops.wm.collada_import(filepath=filename)
			obj = context.active_object
		elif extension.lower() == ".lwo":
			# lwo importer doesn't select or make active the object in creates...
			# need to diff scene objects before and after import to find it
			obj_names = []
			for obj in context.scene.objects:
				obj_names.append(obj.name)
			bpy.ops.import_scene.lwo(filepath=filename, USE_EXISTING_MATERIALS=True)
			imported_obj = None
			for obj in context.scene.objects:
				if not obj.name in obj_names:
					imported_obj = obj
					break
			if not imported_obj:
				return (None, "Importing \"%s\" failed" % filename) # import must have failed
			obj = imported_obj
		# fixup material names by removing filename extensions.
		# e.g. "models/items/rocket_ammo/rocket_large.tga" should be "models/items/rocket_ammo/rocket_large"
		for i, mat in enumerate(obj.data.materials):
			(name, ext) = os.path.splitext(mat.name)
			if ext != "":
				# if a material with the fixed name already exists, use it
				# otherwise rename this one
				new_mat = bpy.data.materials.get(name)
				if new_mat:
					obj.data.materials[i] = new_mat
				else:
					mat.name = name
	context.scene.objects.active = obj
	obj.select = True
	obj.bfg.entity_model = relative_path
	obj.scale = [_scale_to_blender, _scale_to_blender, _scale_to_blender]
	obj.lock_scale = [True, True, True]
	refresh_selected_objects_materials(context)
	return (obj, None)
		
################################################################################
## ENTITIES
################################################################################

class EntityDictPropGroup(bpy.types.PropertyGroup):
	# name property inherited
	value = bpy.props.StringProperty()

class EntityPropGroup(bpy.types.PropertyGroup):
	# name property inherited
	dict = bpy.props.CollectionProperty(type=EntityDictPropGroup)
	
	def get_dict_value(self, key, key_default=None):
		kvp = self.dict.get(key)
		if kvp:
			return kvp.value
		return key_default

class ImportEntities(bpy.types.Operator):
	bl_idname = "scene.import_entities"
	bl_label = "Import Entities"
	
	def parse_def_file(self, scene, filename):
		lex = lexer.Lexer(filename)
		num_entities_created = 0
		num_entities_updated = 0
		print("Parsing", os.path.basename(filename), "...", end="", flush=True)
		while True:
			token = lex.parse_token()
			if token == None:
				break
			if not token == "entityDef":
				name = lex.parse_token() # name, sometimes opening brace
				lex.skip_bracket_delimiter_section("{", "}", True if name == "{" else False)
			else:
				name = lex.parse_token()
				if name in scene.bfg.entities:
					entity = scene.bfg.entities[name]
					num_entities_updated += 1
				else:
					entity = scene.bfg.entities.add()
					entity.name = name
					num_entities_created += 1
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
					elif token.startswith("editor_") or token in ["inherit", "model"]: # only store what we care about
						# parse as key-value pair
						key = token
						if key in entity.dict:
							kvp = entity.dict[key]
						else:
							kvp = entity.dict.add()
							kvp.name = key
						kvp.value = lex.parse_token()
		print(" %d entities" % (num_entities_created + num_entities_updated))
		return (num_entities_created, num_entities_updated)
		
	@classmethod
	def poll(cls, context):
		return context.scene.bfg.game_path != ""
	
	def execute(self, context):
		self.num_entities_created = 0
		self.num_entities_updated = 0
		start_time = time.time() 
		fs = FileSystem()
		files = fs.find_files(os.path.join("def", "*.def"))
		wm = context.window_manager
		wm.progress_begin(0, len(files))
		for i, f in enumerate(files):
			result = self.parse_def_file(context.scene, f)
			wm.progress_update(i)
			self.num_entities_created += result[0]
			self.num_entities_updated += result[1]
		update_scene_entity_properties(context) # update entity objects with any new properties
		wm.progress_end()
		self.report({'INFO'}, "Imported %d entities, updated %d in %.2f seconds" % (self.num_entities_created, self.num_entities_updated, time.time() - start_time))
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
	
def create_object_entity_properties(context, entity, is_inherited=False):
	"""Create entity properties on the active object"""
	for kvp in entity.dict:
		if kvp.name.startswith("editor_var"):
			prop_name = kvp.name.split()[1]
			# prepend "inherited_" to inherited property names
			prop_name = "inherited_" + prop_name
			if not context.active_object.game.properties.get(prop_name):
				# don't create the prop if it already exists
				bpy.ops.object.game_property_new(type='STRING', name=prop_name)
	inherit = entity.dict.get("inherit")
	if inherit:
		parent_entity = context.scene.bfg.entities[inherit.value]
		create_object_entity_properties(context, parent_entity, True)
		
def update_scene_entity_properties(context):
	"""Add missing properties to existing entity objects"""
	for obj in context.scene.objects:
		if obj.bfg.type in ['BRUSH_ENTITY', 'ENTITY']:
			context.scene.objects.active = obj
			entity = context.scene.bfg.entities[obj.bfg.classname]
			create_object_entity_properties(context, entity)
			break

class AddEntity(bpy.types.Operator):
	"""Add a new entity to the scene of the selected type"""
	bl_idname = "scene.add_entity"
	bl_label = "Add Entity"
	
	@classmethod
	def poll(cls, context):
		ae = context.scene.bfg.active_entity
		return ae and ae != ""
	
	def execute(self, context):
		ae = context.scene.bfg.active_entity
		if ae and ae != "":
			active_object = context.active_object
			selected_objects = context.selected_objects
			set_object_mode_and_clear_selection()
			entity = context.scene.bfg.entities[ae]
			entity_mins = entity.get_dict_value("editor_mins", "?")
			entity_maxs = entity.get_dict_value("editor_maxs", "?")
			if entity_mins == "?" or entity_maxs == "?":
				# brush entity, create as empty
				if not (active_object and active_object.bfg.type in ['NONE','BRUSH'] and len(selected_objects) > 0):
					self.report({'ERROR'}, "Brush entities require a brush to be selected")
					return {'CANCELLED'}
				bpy.ops.object.empty_add(type='SPHERE')
				obj = context.active_object
				obj.empty_draw_size = 0.5
				obj.hide_render = True
				obj.location = active_object.location
				obj.lock_rotation = [True, True, True]
				obj.lock_scale = [True, True, True]
				obj.bfg.type = 'BRUSH_ENTITY'
			else:
				# normal entity
				model = entity.get_dict_value("model")
				obj = None
				if model: # create as mesh
					fs = FileSystem()
					filename = fs.find_file_path(model)
					(obj, error_message) = create_model_object(context, filename, model)
					if error_message:
						self.report({'ERROR'}, error_message)
				if not obj: # no model or create_model_object error: fallback to primitive
					bpy.ops.mesh.primitive_cube_add()
					obj = context.active_object
					entity_color = entity.get_dict_value("editor_color", "0 0 1") # default to blue
					obj.color = [float(i) for i in entity_color.split()] + [float(0.5)] # "r g b"
					obj.data.name = ae
					create_object_color_material()
					obj.data.materials.append(bpy.data.materials["_object_color"])
					obj.hide_render = True
					obj.show_wire = True
					obj.show_transparent = True
					
					# set dimensions
					mins = Vector([float(i) * _scale_to_blender for i in entity_mins.split()])
					maxs = Vector([float(i) * _scale_to_blender for i in entity_maxs.split()])
					size = maxs + -mins
					obj.dimensions = size
					
					# set origin
					origin = (mins + maxs) / 2.0
					bpy.ops.object.editmode_toggle()
					bpy.ops.mesh.select_all(action='SELECT')
					bpy.ops.transform.translate(value=origin)
					bpy.ops.object.editmode_toggle()
				obj.lock_rotation = [True, True, False]
				obj.lock_scale = [True, True, True]
				obj.show_axis = True # x will be forward
				obj.show_name = context.scene.bfg.show_entity_names
				obj.bfg.type = 'ENTITY'
			obj.bfg.classname = ae
			obj.name = ae
			link_active_object_to_group("entities")
			create_object_entity_properties(context, entity)
			
			# parent selected objects to this brush entity, and link them to the "entities" group
			# if there is a editor_material for this entity, assign that material to the selected objects
			if obj.bfg.type == 'BRUSH_ENTITY':
				group = bpy.data.groups["entities"]
				mat = None
				mat_name = entity.get_dict_value("editor_material")
				if mat_name:
					mat_decl = context.scene.bfg.material_decls.get(mat_name)
					if mat_decl:
						mat = create_material(mat_decl)
				for s in selected_objects:
					s.location -= obj.location
					s.parent = obj
					group.objects.link(s)
					if mat:
						assign_material(s, mat)
		return {'FINISHED'}
		
class ShowEntityDescription(bpy.types.Operator):
	"""Show entity description"""
	bl_idname = "object.show_entity_description"
	bl_label = "Show Entity Description"
	bl_options = {'REGISTER','UNDO','INTERNAL'}
	
	def draw(self, context):
		bfg = context.scene.bfg
		ent = bfg.entities[bfg.active_entity]
		ent_usage = ent.get_dict_value("editor_usage")
		col = self.layout.column()
		#col.label(ent_usage)
		# no support for text wrapping and multiline labels...
		n = 50
		for i in range(0, len(ent_usage), n):
			col.label(ent_usage[i:i+n])
				
	@classmethod
	def poll(cls, context):
		ae = context.scene.bfg.active_entity
		if ae and ae != "ae":
			ent = context.scene.bfg.entities[ae]
			return ent.dict.get("editor_usage") != None
		return False

	def invoke(self, context, event):
		return context.window_manager.invoke_popup(self)

	def execute(self, context):
		return {'FINISHED'}
		
class ShowEntityPropertyDescription(bpy.types.Operator):
	"""Show entity property description"""
	bl_idname = "object.show_entity_property_description"
	bl_label = "Show Entity Property Description"
	bl_options = {'REGISTER','UNDO','INTERNAL'}
	classname = bpy.props.StringProperty(default="")
	name = bpy.props.StringProperty(default="")
	
	def find_prop_info(self, context, entity):
		info = entity.get_dict_value("editor_var " + self.name)
		if info:
			return info
		inherit = entity.dict.get("inherit")
		if inherit:
			parent_entity = context.scene.bfg.entities[inherit.value]
			return self.find_prop_info(context, parent_entity)
		return None

	def draw(self, context):
		col = self.layout.column()
		if self.classname != "" and self.name != "":
			entity = context.scene.bfg.entities[self.classname]
			info = self.find_prop_info(context, entity)
			if not info:
				info = "No info"
			#col.label(info)
			# no support for text wrapping and multiline labels...
			n = 50
			for i in range(0, len(info), n):
				col.label(info[i:i+n])
				
	def invoke(self, context, event):
		return context.window_manager.invoke_popup(self)

	def execute(self, context):
		return {'FINISHED'}
		
class NewCustomEntityProperty(bpy.types.Operator):
	"""Create a new custom entity property"""
	bl_idname = "scene.new_custom_entity_property"
	bl_label = "New Entity Property"
	bl_options = {'REGISTER','UNDO','INTERNAL'}
	name = bpy.props.StringProperty(name="Name", default="")
	value = bpy.props.StringProperty(name="Value", default="")
	
	def invoke(self, context, event):
		return context.window_manager.invoke_props_dialog(self)

	def execute(self, context):
		if self.name == "":
			return {'CANCELLED'}
		obj = context.active_object
		# handle brush entities. the parent owns the properties
		old_active = None
		if obj.parent and obj.parent.bfg.type == 'BRUSH_ENTITY':
			old_active = context.scene.objects.active
			obj = obj.parent
			context.scene.objects.active = obj
		# check if a normal property already exists with this name
		prop = obj.game.properties.get(self.name)
		if not prop:
			# check if an inherited property already exists with this name
			prop = obj.game.properties.get("inherited_" + self.name)
			if prop:
				# show inherited properties
				context.scene.bfg.show_inherited_entity_props = True
			else:
				# check if a custom property already exists with this name
				prop_name = "custom_" + self.name
				prop = obj.game.properties.get(prop_name)
				if not prop:
					# finally, create the property
					bpy.ops.object.game_property_new(type='STRING', name=prop_name)
					prop = obj.game.properties[prop_name]
		# whether the property has been created, or already exists, set the value	
		prop.value = self.value
		# restore active object
		if old_active:
			context.scene.objects.active = old_active
		else:
			context.scene.objects.active = obj # force ui refresh. game_property_new doesn't seem to trigger it.
		return {'FINISHED'}
		
class RemoveCustomEntityProperty(bpy.types.Operator):
	"""Remove a custom entity property"""
	bl_idname = "scene.remove_custom_entity_property"
	bl_label = "Remove Entity Property"
	bl_options = {'REGISTER','UNDO','INTERNAL'}
	name = bpy.props.StringProperty(default="")
	
	def execute(self, context):
		obj = context.active_object
		# handle brush entities. the parent owns the properties
		old_active = None
		if obj.parent and obj.parent.bfg.type == 'BRUSH_ENTITY':
			old_active = context.scene.objects.active
			obj = obj.parent
			context.scene.objects.active = obj
		prop_index = obj.game.properties.find(self.name)
		if prop_index != -1:
			bpy.ops.object.game_property_remove(index=prop_index)
		# restore active object
		if old_active:
			context.scene.objects.active = old_active
		return {'FINISHED'}
		
################################################################################
## LIGHTS
################################################################################
		
class AddLight(bpy.types.Operator):
	bl_idname = "scene.add_light"
	bl_label = "Add Light"
	
	def execute(self, context):
		set_object_mode_and_clear_selection()
		data = bpy.data.lamps.new(name="Light", type='POINT')
		obj = bpy.data.objects.new(name="Light", object_data=data)
		context.scene.objects.link(obj)
		obj.select = True
		context.scene.objects.active = obj
		obj.data.distance = 300.0 * _scale_to_blender
		obj.data.energy = obj.data.distance
		#obj.scale = obj.distance
		#obj.show_bounds = True
		#obj.draw_bounds_type = 'SPHERE'
		obj.data.use_sphere = True
		link_active_object_to_group("lights")
		return {'FINISHED'}
		
def get_light_radius(self):
	return self.data.distance
	
def set_light_radius(self, value):
	self.data.distance = value
	self.data.energy = value
	
def light_material_preview_items(self, context):
	lights = []
	pcoll = preview_collections["light"]
	if not pcoll.needs_refresh:
		return pcoll.lights
	fs = FileSystem()
	lights.append(("default", "default", "default", 0, 0))
	i = 1
	for decl in context.scene.bfg.material_decls:
		# material name must start with "lights" and have a texture
		if os.path.dirname(decl.name).startswith("lights") and decl.texture != "":
			preview = None
			if decl.texture in pcoll: # workaround blender bug, pcoll.load is supposed to return cached preview if name already exists
				preview = pcoll[decl.texture]
			else:
				filename = fs.find_image_file_path(decl.texture)
				if filename:
					preview = pcoll.load(decl.texture, filename, 'IMAGE')
				elif context.scene.bfg.hide_bad_materials:
					continue # hide if the texture file is missing
			lights.append((decl.name, os.path.basename(decl.name), decl.name, preview.icon_id if preview else 0, i))
			i += 1
	lights.sort()
	pcoll.lights = lights
	pcoll.needs_refresh = False
	return pcoll.lights
	
################################################################################
## STATIC MODELS
################################################################################
		
class AddStaticModel(bpy.types.Operator):
	"""Browse for a static model to add"""
	bl_idname = "scene.add_static_model"
	bl_label = "Add Static Model"
	filepath = bpy.props.StringProperty(default="", options={'HIDDEN', 'SKIP_SAVE'})
	filter_glob = bpy.props.StringProperty(default="*.dae;*.lwo", options={'HIDDEN'})
	
	@classmethod
	def poll(cls, context):
		return context.scene.bfg.game_path != ""
	
	def execute(self, context):
		# the func_static entity model value looks like this
		# "models/mapobjects/arcade_machine/arcade_machine.lwo"
		# so the file path must descend from one of the search paths
		fs = FileSystem()
		relative_path = fs.calculate_relative_path(self.properties.filepath)
		if not relative_path:
			self.report({'ERROR'}, "File \"%s\" not found. Path must descend from \"%s\"" % (self.properties.filepath, context.scene.bfg.game_path))
			return {'CANCELLED'}
		(obj, error_message) = create_model_object(context, self.properties.filepath, relative_path)
		if error_message:
			self.report({'ERROR'}, error_message)
			return {'CANCELLED'}
		else:
			obj.bfg.type = 'STATIC_MODEL'
			obj.bfg.classname = "func_static"
			link_active_object_to_group("static models")
		return {'FINISHED'}

	def invoke(self, context, event):
		context.window_manager.fileselect_add(self)
		return {'RUNNING_MODAL'}
	
################################################################################
## MAP
################################################################################

def update_room_plane_modifier(obj):
	if obj.modifiers:
		mod = obj.modifiers[0]
		if mod.type == 'SOLIDIFY':
			mod.thickness = obj.bfg.room_height
			mod.material_offset = 1
			mod.material_offset_rim = 2

def update_room_plane_materials(obj):
	if bpy.data.materials.find(obj.bfg.floor_material) != -1:
		obj.material_slots[0].material = bpy.data.materials[obj.bfg.floor_material]
	if bpy.data.materials.find(obj.bfg.ceiling_material) != -1:
		obj.material_slots[1].material = bpy.data.materials[obj.bfg.ceiling_material]
	if bpy.data.materials.find(obj.bfg.wall_material) != -1:
		obj.material_slots[2].material = bpy.data.materials[obj.bfg.wall_material]

def update_room(self, context):
	obj = context.active_object
	if obj.bfg.type == '2D_ROOM':
		update_room_plane_modifier(obj)
		update_room_plane_materials(obj)
		
def flip_mesh_normals(mesh):
	bm = bmesh.new()
	bm.from_mesh(mesh)
	for f in bm.faces:
		f.normal_flip()
	bm.to_mesh(mesh)
	bm.free()
	
def apply_boolean(dest, src, bool_op, flip_normals=False):
	# auto unwrap this 3D room or brush if that's what the user wants
	if src.bfg.type in ['3D_ROOM', 'BRUSH'] and src.bfg.auto_unwrap:
		auto_unwrap(src.data, src.location, src.scale)
		
	# generate mesh for the source object
	# transform to worldspace
	bpy.ops.object.select_all(action='DESELECT')
	dest.select = True
	me = src.to_mesh(bpy.context.scene, True, 'PREVIEW')
	me.transform(src.matrix_world)
	
	# 2D rooms are always unwrapped (the to_mesh result, not the object - it's just a plane)
	if src.bfg.type == '2D_ROOM':
		auto_unwrap(me)
		
	if flip_normals:
		flip_mesh_normals(me)
		
	# bool object - need a temp object to hold the result of to_mesh
	ob_bool = bpy.data.objects.new("_bool", me)
	
	# copy materials
	for mat in src.data.materials:
		if not mat.name in dest.data.materials:
			dest.data.materials.append(mat)	
	
	# apply the boolean modifier
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
		
def build_map(context, rooms, brushes, map_name):
	scene = context.scene

	# get all the temp bool objects from the last time this map was built
	bool_objects = [obj for obj in bpy.data.objects if obj.name.startswith(map_name + "_bool")]
				
	# create map object
	# if a map object already exists, its old mesh is removed
	set_object_mode_and_clear_selection()
	old_map_mesh = None
	map_mesh_name = map_name + "_mesh"
	if map_mesh_name in bpy.data.meshes:
		old_map_mesh = bpy.data.meshes[map_mesh_name]
		old_map_mesh.name = "_worldspawn_old"
	if len(rooms) > 0:
		# first room: generate the mesh and transform to worldspace
		if rooms[0].bfg.type == '3D_ROOM' and rooms[0].bfg.auto_unwrap:
			auto_unwrap(rooms[0].data)
		map_mesh = rooms[0].to_mesh(scene, True, 'PREVIEW')
		map_mesh.name = map_mesh_name
		map_mesh.transform(rooms[0].matrix_world)
		
		# 2D rooms are always unwrapped (the to_mesh result, not the object - it's just a plane)
		if rooms[0].bfg.type == '2D_ROOM':
			auto_unwrap(map_mesh)
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
	map.hide = False
				
	# combine rooms
	if len(rooms) > 0:
		flip_object_normals(map)
	for i, room in enumerate(rooms):
		if i > 0:
			# not the first room: bool union with existing mesh
			apply_boolean(map, room, 'UNION', flip_normals=True)
	map.select = True
	if len(rooms) > 0:
		flip_object_normals(map)
		
	# combine brushes
	for brush in brushes:
		apply_boolean(map, brush, 'UNION')
		
	link_active_object_to_group("map")
	move_object_to_layer(map, scene.bfg.map_layer)
	map.hide_select = True
	bpy.ops.object.select_all(action='DESELECT')
	
	# cleanup temp bool objects
	for obj in bool_objects:
		mesh = obj.data
		bpy.data.objects.remove(obj)
		bpy.data.meshes.remove(mesh)
		
class AddRoom(bpy.types.Operator):
	bl_idname = "scene.add_room"
	bl_label = "Add Room"

	def execute(self, context):
		scene = context.scene
		set_object_mode_and_clear_selection()
		bpy.ops.mesh.primitive_plane_add(radius=1)
		bpy.ops.object.modifier_add(type='SOLIDIFY')
		obj = context.active_object
		obj.lock_scale = [False, False, True]
		obj.modifiers[0].offset = 1
		obj.modifiers[0].use_even_offset = True
		obj.modifiers[0].use_flip_normals = True
		obj.modifiers[0].use_quality_normals = True
		obj.name = "room2D"
		obj.data.name = "room2D"
		obj.bfg.room_height = 4
		obj.bfg.type = '2D_ROOM'
		if context.scene.bfg.wireframe_rooms:
			obj.draw_type = 'WIRE'
		obj.game.physics_type = 'NO_COLLISION'
		obj.hide_render = True
		if len(bpy.data.materials) > 0:
			mat = get_or_create_active_material(context)
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
		set_object_mode_and_clear_selection()
		bpy.ops.mesh.primitive_cube_add(radius=1)
		obj = context.active_object
		if context.scene.bfg.wireframe_rooms:
			obj.draw_type = 'WIRE'
		if self.s_type == '3D_ROOM':
			obj.name = "room3D"
			obj.data.name = "room3D"
		else:
			obj.name = "brush"
			obj.data.name = "brush"
		obj.bfg.type = self.s_type
		mat = get_or_create_active_material(context)
		if mat:
			obj.data.materials.append(mat)
		scene.objects.active = obj
		bpy.ops.object.editmode_toggle()
		bpy.ops.mesh.select_all(action='SELECT')
		bpy.ops.object.auto_uv_unwrap()
		bpy.ops.object.editmode_toggle()
		obj.game.physics_type = 'NO_COLLISION'
		obj.hide_render = True
		if self.s_type == '3D_ROOM':
			flip_object_normals(obj)
			link_active_object_to_group("rooms")
		else:
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
			if s.bfg.type == '2D_ROOM':
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
		
class ConvertRoom(bpy.types.Operator):
	"""Convert the selected 2D room(s) to 3D room(s)"""
	bl_idname = "scene.convert_room"
	bl_label = "Convert Room"
	
	def execute(self, context):
		selected_objects = list(context.selected_objects) # copy the list, selected objects will change
		for obj in selected_objects:
			if obj.bfg.type == '2D_ROOM':
				obj.bfg.type = '3D_ROOM'
				
				# create a new mesh, applying the solidify modifer
				# swap the old mesh with the new one, preserving the name
				# then delete the old mesh
				old_mesh = obj.data
				new_mesh_name = old_mesh.name
				old_mesh.name = "_temp" + old_mesh.name
				new_mesh = obj.to_mesh(context.scene, True, 'PREVIEW')
				new_mesh.name = new_mesh_name
				obj.data = new_mesh
				bpy.data.meshes.remove(old_mesh)
				
				# remove the solidify modifier
				context.scene.objects.active = obj
				bpy.ops.object.modifier_remove(modifier=obj.modifiers[0].name)
				
				# 2D room UVs are never valid, so unwrap
				bpy.ops.object.auto_uv_unwrap()
		return {'FINISHED'}

class BuildMap(bpy.types.Operator):
	bl_idname = "scene.build_map"
	bl_label = "Build Map"
	bool_op = bpy.props.StringProperty(name="bool_op", default='INTERSECT')

	def execute(self, context):
		# worldspawn
		rooms = []
		brushes = []
		for obj in context.scene.objects:
			if obj.parent and obj.parent.bfg.type == 'BRUSH_ENTITY':
				continue # ignore children of brush entities
			if obj.bfg.type in ['2D_ROOM', '3D_ROOM']:
				rooms.append(obj)
			elif obj.bfg.type == 'BRUSH':
				brushes.append(obj)
					
		build_map(context, rooms, brushes, "_worldspawn")
		
		# brush entities
		for obj in context.scene.objects:
			if obj.bfg.type == 'BRUSH_ENTITY':
				brushes = []
				for child in obj.children:
					if child.bfg.type == 'BRUSH':
						brushes.append(child)
				if len(brushes) > 0:
					build_map(context, [], brushes, "_" + obj.name)
		return {'FINISHED'}
		
################################################################################
## UV UNWRAPPING
################################################################################

def auto_unwrap(mesh, obj_location=Vector(), obj_scale=Vector((1, 1, 1))):
	if bpy.context.mode == 'EDIT_MESH':
		bm = bmesh.from_edit_mesh(mesh)
	else:
		bm = bmesh.new()
		bm.from_mesh(mesh)
	uv_layer = bm.loops.layers.uv.verify()
	bm.faces.layers.tex.verify()  # currently blender needs both layers.
	for f in bm.faces:
		if bpy.context.mode == 'EDIT_MESH' and not f.select:
			continue # ignore faces that aren't selected in edit mode
		texture_size = (128, 128)
		mat = mesh.materials[f.material_index]
		if len(mat.texture_slots) > 0:
			tex = bpy.data.textures[mat.texture_slots[0].name]
			if hasattr(tex, "image") and tex.image: # if the texture type isn't set to "Image or Movie", the image attribute won't exist
				texture_size = tex.image.size
		nX = f.normal.x
		nY = f.normal.y
		nZ = f.normal.z
		if nX < 0:
			nX = nX * -1
		if nY < 0:
			nY = nY * -1
		if nZ < 0:
			nZ = nZ * -1
		face_normal_largest = nX
		face_direction = 'x'
		if face_normal_largest < nY:
			face_normal_largest = nY
			face_direction = 'y'
		if face_normal_largest < nZ:
			face_normal_largest = nZ
			face_direction = 'z'
		if face_direction == 'x':
			if f.normal.x < 0:
				face_direction = '-x'
		if face_direction == 'y':
			if f.normal.y < 0:
				face_direction = '-y'
		if face_direction == 'z':
			if f.normal.z < 0:
				face_direction = '-z'
		scale_x = _scale_to_game / texture_size[0] * (1.0 / bpy.context.scene.bfg.global_uv_scale)
		scale_y = _scale_to_game / texture_size[1] * (1.0 / bpy.context.scene.bfg.global_uv_scale)
		for l in f.loops:
			luv = l[uv_layer]
			if luv.pin_uv is not True:
				if face_direction == 'x':
					luv.uv.x = ((l.vert.co.y * obj_scale[1]) + obj_location[1]) * scale_x
					luv.uv.y = ((l.vert.co.z * obj_scale[2]) + obj_location[2]) * scale_y
				if face_direction == '-x':
					luv.uv.x = (((l.vert.co.y * obj_scale[1]) + obj_location[1]) * scale_x) * -1
					luv.uv.y = ((l.vert.co.z * obj_scale[2]) + obj_location[2]) * scale_y
				if face_direction == 'y':
					luv.uv.x = (((l.vert.co.x * obj_scale[0]) + obj_location[0]) * scale_x) * -1
					luv.uv.y = ((l.vert.co.z * obj_scale[2]) + obj_location[2]) * scale_y
				if face_direction == '-y':
					luv.uv.x = ((l.vert.co.x * obj_scale[0]) + obj_location[0]) * scale_x
					luv.uv.y = ((l.vert.co.z * obj_scale[2]) + obj_location[2]) * scale_y
				if face_direction == 'z':
					luv.uv.x = ((l.vert.co.x * obj_scale[0]) + obj_location[0]) * scale_x
					luv.uv.y = ((l.vert.co.y * obj_scale[1]) + obj_location[1]) * scale_y
				if face_direction == '-z':
					luv.uv.x = (((l.vert.co.x * obj_scale[0]) + obj_location[0]) * scale_x) * 1
					luv.uv.y = (((l.vert.co.y * obj_scale[1]) + obj_location[1]) * scale_y) * -1
	if bpy.context.mode == 'EDIT_MESH':
		bmesh.update_edit_mesh(mesh)
	else:
		bm.to_mesh(mesh)
		bm.free()
		mesh.update()

class AutoUnwrap(bpy.types.Operator):
	bl_idname = "object.auto_uv_unwrap"
	bl_label = "Auto Unwrap"
	bl_options = {'REGISTER','UNDO'}
	
	@classmethod
	def poll(cls, context):
		return bpy.context.mode in ['EDIT_MESH', 'OBJECT']

	def execute(self, context):
		obj = context.active_object
		auto_unwrap(obj.data, obj.location, obj.scale)
		return {'FINISHED'}
		
class FitUV(bpy.types.Operator):
	"""Fit the selected face UVs to the texture dimensions along the specified axis"""
	bl_idname = "object.uv_fit"
	bl_label = "Fit UV"
	bl_options = {'REGISTER','UNDO'}
	axis = bpy.props.StringProperty(name="Axis", default='BOTH')
	
	@classmethod
	def poll(cls, context):
		return context.mode == 'EDIT_MESH'

	def execute(self, context):
		obj = context.active_object
		bm = bmesh.from_edit_mesh(obj.data)
		uv_layer = bm.loops.layers.uv.active
		if not uv_layer:
			return {'CANCELLED'}
		for f in bm.faces:
			if not f.select:
				continue
			# calculate min/max
			min = [None, None]
			max = [None, None]
			for l in f.loops:
				uv = l[uv_layer].uv
				if self.axis in ['HORIZONTAL', 'BOTH']:
					min[0] = min_nullable(min[0], uv.x)
					max[0] = max_nullable(max[0], uv.x)
				if self.axis in ['VERTICAL', 'BOTH']:
					min[1] = min_nullable(min[1], uv.y)
					max[1] = max_nullable(max[1], uv.y)
			# apply fitting
			for l in f.loops:
				uv = l[uv_layer].uv
				if self.axis in ['HORIZONTAL', 'BOTH']:
					range = max[0] - min[0]
					if range != 0: # will be 0 if UVs are uninitialized
						uv.x = uv.x / range * context.scene.bfg.uv_fit_repeat
				if self.axis in ['VERTICAL', 'BOTH']:
					range = max[1] - min[1]
					if range != 0: # will be 0 if UVs are uninitialized
						uv.y = uv.y / range * context.scene.bfg.uv_fit_repeat
		bmesh.update_edit_mesh(obj.data)
		return {'FINISHED'}
		
class FlipUV(bpy.types.Operator):
	"""Flip the selected face UVs along the specified axis"""
	bl_idname = "object.uv_flip"
	bl_label = "Flip UV"
	bl_options = {'REGISTER','UNDO'}
	axis = bpy.props.StringProperty(name="Axis", default='HORIZONTAL')
	
	@classmethod
	def poll(cls, context):
		return context.mode == 'EDIT_MESH'

	def execute(self, context):
		prev_area = context.area.type
		context.area.type = 'IMAGE_EDITOR'
		bpy.ops.uv.select_all(action='SELECT')
		if self.axis == 'HORIZONTAL':
			bpy.ops.transform.resize(value=(-1, 1, 1))
		elif self.axis == 'VERTICAL':
			bpy.ops.transform.resize(value=(1, -1, 1))
		context.area.type = prev_area
		return {'FINISHED'}

class NudgeUV(bpy.types.Operator):
	"""Nudge the selected face UVs in the specified direction"""
	bl_idname = "object.uv_nudge"
	bl_label = "Nudge UV"
	bl_options = {'REGISTER','UNDO'}
	dir = bpy.props.StringProperty(name="Direction", default='LEFT')
	
	@classmethod
	def poll(cls, context):
		return context.mode == 'EDIT_MESH'

	def execute(self, context):
		prev_area = context.area.type
		context.area.type = 'IMAGE_EDITOR'
		bpy.ops.uv.select_all(action='SELECT')
		if self.dir == 'LEFT':
			bpy.ops.transform.translate(value=(context.scene.bfg.uv_nudge_increment, 0, 0))
		elif self.dir == 'RIGHT':
			bpy.ops.transform.translate(value=(-context.scene.bfg.uv_nudge_increment, 0, 0))
		elif self.dir == 'UP':
			bpy.ops.transform.translate(value=(0, -context.scene.bfg.uv_nudge_increment, 0))
		elif self.dir == 'DOWN':
			bpy.ops.transform.translate(value=(0, context.scene.bfg.uv_nudge_increment, 0))
		context.area.type = prev_area
		return {'FINISHED'}
		
def is_uv_flipped(context):
	# just the first face
	obj = context.active_object
	bm = bmesh.from_edit_mesh(obj.data)
	uv_layer = bm.loops.layers.uv.active
	if uv_layer:
		for f in bm.faces:
			if not f.select:
				continue
			v1 = f.loops[1][uv_layer].uv - f.loops[0][uv_layer].uv
			v2 = f.loops[2][uv_layer].uv - f.loops[1][uv_layer].uv
			if v1.cross(v2) >= 0:
				return False
			else:
				return True
	return False
			
class RotateUV(bpy.types.Operator):
	"""Rotate the selected face UVs"""
	bl_idname = "object.uv_rotate"
	bl_label = "Rotate UV"
	bl_options = {'REGISTER','UNDO'}
	dir = bpy.props.StringProperty(name="Direction", default='HORIZONTAL')
	
	@classmethod
	def poll(cls, context):
		return context.mode == 'EDIT_MESH'

	def execute(self, context):
		prev_area = context.area.type
		context.area.type = 'IMAGE_EDITOR'
		bpy.ops.uv.select_all(action='SELECT')
		degrees = context.scene.bfg.uv_rotate_degrees
		if self.dir == 'RIGHT':
			degrees *= -1
		if is_uv_flipped(context):
			degrees *= -1 # swap left and right if the face normal is flipped
		bpy.ops.transform.rotate(value=math.radians(degrees))
		context.area.type = prev_area
		return {'FINISHED'}
		
################################################################################
## GUI PANELS
################################################################################
		
class SettingsPanel(bpy.types.Panel):
	bl_label = "Settings"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"

	def draw(self, context):
		scene = context.scene
		col = self.layout.column(align=True)
		col.prop(scene.bfg, "game_path", "Path")
		col.prop(scene.bfg, "mod_dir")
		col.operator(ImportMaterials.bl_idname, ImportMaterials.bl_label, icon='MATERIAL')
		col.operator(ImportEntities.bl_idname, ImportEntities.bl_label, icon='POSE_HLT')
		flow = col.column_flow(2)
		flow.prop(scene.bfg, "wireframe_rooms")
		flow.prop(scene.bfg, "backface_culling")
		flow.prop(scene.bfg, "show_entity_names")
		flow.prop(scene.bfg, "hide_bad_materials")
		flow.prop(scene.bfg, "shadeless_materials")
		col.prop(context.scene.bfg, "global_uv_scale")
		
class CreatePanel(bpy.types.Panel):
	bl_label = "Create"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"
	
	def draw(self, context):
		scene = context.scene
		col = self.layout.column(align=True)
		row = col.row(align=True)
		row.operator(BuildMap.bl_idname, "Build Map", icon='MOD_BUILD').bool_op = 'UNION'
		row.prop(context.scene.bfg, "map_layer")
		col.operator(AddRoom.bl_idname, "Add 2D Room", icon='SURFACE_NCURVE')
		col.operator(AddBrush.bl_idname, "Add 3D Room", icon='SNAP_FACE').s_type = '3D_ROOM'
		col.operator(AddBrush.bl_idname, "Add Brush", icon='SNAP_VOLUME').s_type = 'BRUSH'
		col = self.layout.column()
		if len(scene.bfg.entities) > 0:
			row = col.row(align=True)
			row.prop_search(scene.bfg, "active_entity", scene.bfg, "entities", "", icon='POSE_HLT')
			row.operator(ShowEntityDescription.bl_idname, "", icon='INFO')
			row.operator(AddEntity.bl_idname, "", icon='ZOOMIN')
		col.operator(AddLight.bl_idname, AddLight.bl_label, icon='LAMP_POINT')
		col.operator(AddStaticModel.bl_idname, AddStaticModel.bl_label, icon='MESH_MONKEY')
		
class MaterialPanel(bpy.types.Panel):
	bl_label = "Material"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"
	
	def draw(self, context):
		scene = context.scene
		if len(scene.bfg.material_decls) > 0:
			col = self.layout.column()
			col.prop_search(scene.bfg, "active_material_decl_path", scene.bfg, "material_decl_paths", "", icon='MATERIAL')
			col.template_icon_view(scene.bfg, "active_material_decl")
			col.prop(scene.bfg, "active_material_decl", "")
			obj = context.active_object
			if obj and len(context.selected_objects) > 0:
				if obj.bfg.type == '2D_ROOM':
					col.label("Assign:", icon='MATERIAL')
					row = col.row(align=True)
					row.operator(AssignMaterial.bl_idname, "Ceiling").where = 'CEILING'
					row.operator(AssignMaterial.bl_idname, "Wall").where = 'WALL'
					row.operator(AssignMaterial.bl_idname, "Floor").where = 'FLOOR'
					row.operator(AssignMaterial.bl_idname, "All").where = 'ALL'
				elif hasattr(obj.data, "materials") or len(context.selected_objects) > 1: # don't hide if multiple selections
					col.operator(AssignMaterial.bl_idname, AssignMaterial.bl_label, icon='MATERIAL')

class ObjectPanel(bpy.types.Panel):
	bl_label = "Object"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"
	
	def draw_object_label(self, col, obj):
		obj_icon = 'OBJECT_DATAMODE'
		if obj.type == 'LAMP':
			obj_icon = 'LAMP_POINT'
		elif obj.bfg.type in ['BRUSH_ENTITY','ENTITY']:
			obj_icon = 'POSE_HLT'
		obj_label = ""
		if obj.bfg.type != 'NONE':
			obj_label += obj.bfg.bl_rna.properties['type'].enum_items[obj.bfg.type].name + ": "
		obj_label += obj.name
		col.label(obj_label, icon=obj_icon)
	
	def draw_entity_properties(self, context, col, obj):
		col.prop(context.scene.bfg, "show_inherited_entity_props")
		for prop in obj.game.properties:
			is_inherited = prop.name.startswith("inherited_")
			if not context.scene.bfg.show_inherited_entity_props and is_inherited:
				continue # user doesn't want to see inherited props
			is_custom = prop.name.startswith("custom_")
			row = col.row(align=True)
			name = prop.name
			if is_inherited:
				name = name[len("inherited_"):] # remove the prefix
			elif is_custom:
				name = name[len("custom_"):] # remove the prefix
			row.label(name + ":")
			row.prop(prop, "value", text="")
			props = row.operator(ShowEntityPropertyDescription.bl_idname, "", icon='INFO')
			props.classname = obj.bfg.classname
			props.name = name
			if is_custom:
				# custom properties can be removed
				row.operator(RemoveCustomEntityProperty.bl_idname, "", icon='X').name = prop.name
		col.operator(NewCustomEntityProperty.bl_idname, NewCustomEntityProperty.bl_label, icon='ZOOMIN')

	def draw(self, context):
		obj = context.active_object
		if obj and len(context.selected_objects) > 0:
			col = self.layout.column()
			self.draw_object_label(col, obj)
			if obj.bfg.type == '2D_ROOM':
				sub = col.column(align=True)
				sub.prop(obj.bfg, "room_height")
				sub.operator(CopyRoom.bl_idname, "Copy Room Height", icon='PASTEFLIPUP').copy_op = 'HEIGHT'
				sub = col.column()
				sub.enabled = False
				sub.prop(obj.bfg, "ceiling_material", "Ceiling")
				sub.prop(obj.bfg, "wall_material", "Wall")
				sub.prop(obj.bfg, "floor_material", "Floor")
				col.label("Copy Materials:", icon='PASTEFLIPUP')
				row = col.row(align=True)
				row.operator(CopyRoom.bl_idname, "Ceiling").copy_op = 'MATERIAL_CEILING'
				row.operator(CopyRoom.bl_idname, "Wall").copy_op = 'MATERIAL_WALL'
				row.operator(CopyRoom.bl_idname, "Floor").copy_op = 'MATERIAL_FLOOR'
				row.operator(CopyRoom.bl_idname, "All").copy_op = 'MATERIAL_ALL'
				col.operator(ConvertRoom.bl_idname, ConvertRoom.bl_label, icon='SNAP_FACE')
			elif obj.bfg.type in ['3D_ROOM', 'BRUSH']:
				col.prop(obj.bfg, "auto_unwrap")
			elif obj.bfg.type in ['BRUSH_ENTITY','ENTITY']:
				self.draw_entity_properties(context, col, obj)
			elif obj.type == 'LAMP':
				row = col.row()
				row.prop(obj, "bfg_light_radius")
				row.prop(obj.data, "color", "")
				col.prop(obj.data, "use_specular")
				col.prop(obj.data, "use_diffuse")
				col.template_icon_view(obj.bfg, "light_material")
				col.prop(obj.bfg, "light_material", "")
			if hasattr(obj.data, "materials") or len(context.selected_objects) > 1: # don't hide if multiple selections
				col.operator(RefreshMaterials.bl_idname, RefreshMaterials.bl_label, icon='MATERIAL')
			# if this object is part of a brush entity (i.e. a child of one), show the brush entity properties
			if obj.parent and obj.parent.bfg.type == 'BRUSH_ENTITY':
				self.draw_object_label(col, obj.parent)
				self.draw_entity_properties(context, col, obj.parent)

class UvPanel(bpy.types.Panel):
	bl_label = "UV"
	bl_space_type = 'VIEW_3D'
	bl_region_type = 'TOOLS'
	bl_category = "BFGForge"

	def draw(self, context):
		obj = context.active_object
		if not obj or len(context.selected_objects) == 0 or not hasattr(obj.data, "materials"):
			return
		col = self.layout.column(align=True)
		col.operator(AutoUnwrap.bl_idname, AutoUnwrap.bl_label, icon='UV_FACESEL')
		if context.mode != 'EDIT_MESH':
			return
		col.separator()
		col.label("Nudge", icon='FORWARD')
		row = col.row(align=True)
		row.operator(NudgeUV.bl_idname, "Left").dir = 'LEFT'
		row.operator(NudgeUV.bl_idname, "Right").dir = 'RIGHT'
		row = col.row(align=True)
		row.operator(NudgeUV.bl_idname, "Up").dir = 'UP'
		row.operator(NudgeUV.bl_idname, "Down").dir = 'DOWN'
		col.prop(context.scene.bfg, "uv_nudge_increment", "Increment")
		col.separator()
		col.label("Rotate", icon='FILE_REFRESH')
		row = col.row(align=True)
		row.operator(RotateUV.bl_idname, "Left").dir = 'LEFT'
		row.operator(RotateUV.bl_idname, "Right").dir = 'RIGHT'
		col.prop(context.scene.bfg, "uv_rotate_degrees", "Degrees")
		col.separator()
		col.label("Flip", icon='LOOP_BACK')
		row = col.row(align=True)
		row.operator(FlipUV.bl_idname, "Horizontal").axis = 'HORIZONTAL'
		row.operator(FlipUV.bl_idname, "Vertical").axis = 'VERTICAL'
		col.separator()
		col.label("Fit", icon='FULLSCREEN_ENTER')
		row = col.row(align=True)
		row.operator(FitUV.bl_idname, "Horizontal").axis = 'HORIZONTAL'
		row.operator(FitUV.bl_idname, "Vertical").axis = 'VERTICAL'
		row.operator(FitUV.bl_idname, "Both").axis = 'BOTH'
		col.prop(context.scene.bfg, "uv_fit_repeat", "Repeat")

################################################################################
## PROPERTIES
################################################################################

def update_wireframe_rooms(self, context):
	for obj in context.scene.objects:
		if obj.bfg.type in ['2D_ROOM', '3D_ROOM', 'BRUSH']:
			obj.draw_type = 'WIRE' if context.scene.bfg.wireframe_rooms else 'TEXTURED'
			
def get_backface_culling(self):
	return bpy.context.space_data.show_backface_culling
	
def set_backface_culling(self, value):
	bpy.context.space_data.show_backface_culling = value
			
def update_show_entity_names(self, context):
	for obj in context.scene.objects:
		if obj.bfg.type == 'ENTITY':
			obj.show_name = context.scene.bfg.show_entity_names
			
def update_hide_bad_materials(self, context):
	preview_collections["material"].force_refresh = True
	preview_collections["light"].needs_refresh = True
	
def update_shadeless_materials(self, context):
	for mat in bpy.data.materials:
		mat_path = os.path.dirname(mat.name)
		if mat.name != "_object_color" and mat_path not in _editor_material_paths:
			mat.use_shadeless = context.scene.bfg.shadeless_materials
	
class BfgScenePropertyGroup(bpy.types.PropertyGroup):
	game_path = bpy.props.StringProperty(name="RBDOOM-3-BFG Path", description="RBDOOM-3-BFG Path", subtype='DIR_PATH')
	mod_dir = bpy.props.StringProperty(name="Mod Directory")
	wireframe_rooms = bpy.props.BoolProperty(name="Wireframe rooms", default=True, update=update_wireframe_rooms)
	backface_culling = bpy.props.BoolProperty(name="Backface culling", get=get_backface_culling, set=set_backface_culling)
	show_entity_names = bpy.props.BoolProperty(name="Show entity names", default=False, update=update_show_entity_names)
	hide_bad_materials = bpy.props.BoolProperty(name="Hide bad materials", description="Hide materials with missing diffuse textures", default=True, update=update_hide_bad_materials)
	shadeless_materials = bpy.props.BoolProperty(name="Fullbright materials", description="Disable lighting on materials", default=True, update=update_shadeless_materials)
	show_inherited_entity_props = bpy.props.BoolProperty(name="Show inherited properties", description="Show inherited entity properties", default=False)
	map_layer = bpy.props.IntProperty(name="Layer", default=0, min=0, max=19)
	material_decl_paths = bpy.props.CollectionProperty(type=MaterialDeclPathPropGroup)
	active_material_decl_path = bpy.props.StringProperty(name="", default="")
	material_decls = bpy.props.CollectionProperty(type=MaterialDeclPropGroup)
	active_material_decl = bpy.props.EnumProperty(name="", items=material_decl_preview_items)
	entities = bpy.props.CollectionProperty(type=EntityPropGroup)
	active_entity = bpy.props.StringProperty(name="Active Entity", default="")
	global_uv_scale = bpy.props.FloatProperty(name="Global UV Scale", description="Scale Automatically unwrapped UVs by this amount", default=0.5, step=0.1, min=0.1, max=10)
	uv_fit_repeat = bpy.props.FloatProperty(name="UV Fit Repeat", default=1.0, step=0.1, min=0.1, max=10)
	uv_nudge_increment = bpy.props.FloatProperty(name="Nudge Increment", default=_scale_to_blender)
	uv_rotate_degrees = bpy.props.FloatProperty(name="UV Rotate Degrees", default=90.0, step=10.0, min=1.0, max=90.0)
	
class BfgObjectPropertyGroup(bpy.types.PropertyGroup):
	auto_unwrap = bpy.props.BoolProperty(name="Auto unwrap on Build Map", description="Auto Unwrap this object when the map is built", default=True)
	classname = bpy.props.StringProperty(name="Classname", default="")
	entity_model = bpy.props.StringProperty(name="Entity model", default="")
	room_height = bpy.props.FloatProperty(name="Room Height", default=4, step=20, precision=1, update=update_room)
	floor_material = bpy.props.StringProperty(name="Floor Material", update=update_room)
	wall_material = bpy.props.StringProperty(name="Wall Material", update=update_room)
	ceiling_material = bpy.props.StringProperty(name="Ceiling Material", update=update_room)
	light_material = bpy.props.EnumProperty(name="", items=light_material_preview_items)
	type = bpy.props.EnumProperty(items=[
		('NONE', "None", ""),
		('2D_ROOM', "2D Room", ""),
		('3D_ROOM', "3D Room", ""),
		('BRUSH', "Brush", ""),
		('ENTITY', "Entity", ""),
		('BRUSH_ENTITY', "Brush Entity", ""),
		('STATIC_MODEL', "Static Model", "")
	], name="BFG Forge Object Type", default='NONE')
	
################################################################################
## MAIN
################################################################################
	
def register():
	bpy.types.Scene.bfg = bpy.props.PointerProperty(type=BfgScenePropertyGroup)
	bpy.types.Object.bfg = bpy.props.PointerProperty(type=BfgObjectPropertyGroup)
	# not in BfgObjectPropertyGroup because get/set self object would be BfgObjectPropertyGroup, not bpy.types.Object
	bpy.types.Object.bfg_light_radius = bpy.props.FloatProperty(name="Radius", get=get_light_radius, set=set_light_radius)
	pcoll = bpy.utils.previews.new()
	pcoll.materials = ()
	pcoll.current_decl_path = ""
	pcoll.force_refresh = False
	preview_collections["material"] = pcoll
	pcoll = bpy.utils.previews.new()
	pcoll.lights = ()
	pcoll.needs_refresh = True
	preview_collections["light"] = pcoll

def unregister():
	del bpy.types.Scene.bfg
	del bpy.types.Object.bfg
	del bpy.types.Object.bfg_light_radius
	for pcoll in preview_collections.values():
		bpy.utils.previews.remove(pcoll)
	preview_collections.clear()

if __name__ == "__main__":
	register()
