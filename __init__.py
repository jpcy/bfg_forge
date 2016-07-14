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
	'name': "BFG Forge",
	'description': "RBDOOM-3-BFG mapping tools",
	'author': "Jonathan Young",
	'blender': (2, 75, 0),
	'category': "Game Engine",
	'tracker_url': "https://github.com/jpcy/bfg_forge"
	}
	
# handle reloading
if "bpy" in locals():
	import imp
	imp.reload(core)
	imp.reload(export_map)
	imp.reload(import_md5mesh)
	imp.reload(lexer)
else:
	from . import core, export_map, import_md5mesh, lexer
	
import bpy
	
def register():
	bpy.utils.register_module(__name__)
	core.register()
	export_map.register()

def unregister():
	bpy.utils.unregister_module(__name__)
	core.unregister()
	export_map.unregister()

if __name__ == "__main__":
	register()
