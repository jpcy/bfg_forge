# BFG Forge
https://github.com/jpcy/bfg_forge

A Blender addon for [RBDOOM-3-BFG](https://github.com/RobertBeckebans/RBDOOM-3-BFG) mapping.

Based on [Level Buddy by Matt Lucas](https://matt-lucas.itch.io/level-buddy)

Status: WIP

Requires:
* The [map-primitive-polygons-for-blender branch of RBDOOM-3-BFG](https://github.com/RobertBeckebans/RBDOOM-3-BFG/tree/map-primitive-polygons-for-blender) to compile the exported map.
* Doom 3 with the pk4 files extracted if you want to see textures, since Blender can't read BFG extracted textures. They're DXT compressed with a custom file container.

DONE:
* Basic material decl and entity def parsing
* Selectable material decl with preview image and icons
* Create material from decl
* Create entities - only fixed size ones for now
* Create lights, set properties - partially done
* Use Level Buddy for quickly building a mesh - similar to subtractive and additive brushes
* Use Texture Buddy for simple automatic UV unwrap
* Map file exporter

TODO:
* Cycles materials
* Entity properties
* Per-object/face auto UV unwrap options - try to work similar to Radiant
* Much more...
