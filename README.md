# BFG Forge
https://github.com/jpcy/bfg_forge

A Blender addon for [RBDOOM-3-BFG](https://github.com/RobertBeckebans/RBDOOM-3-BFG) mapping.

Based on [Level Buddy by Matt Lucas](https://matt-lucas.itch.io/level-buddy)

Status: WIP

Requires:
* The [map-primitive-polygons-for-blender branch of RBDOOM-3-BFG](https://github.com/RobertBeckebans/RBDOOM-3-BFG/tree/map-primitive-polygons-for-blender) to compile the exported map.
* Doom 3 with the pk4 files extracted if you want material decl previews, since BFG doesn't ship with qer_editorimage files. BFG extracted textures are DXT compressed use a custom file container which Blender can't read anyway.

DONE:
* Basic material decl and entity def parsing
* Selectable material decl with preview image and icon
* Create material from decl - using qer_editorimage for now
* Create entities - only fixed size ones for now
* Use Level Buddy for quickly building a mesh - similar to subtractive and additive brushes
* Use Texture Buddy for simple automatic UV unwrap
* Basic exporter - only the built map mesh and entities with origin for now

TODO:
* Create materials using diffuse/normal/specular instead of qer_editorimage
* Cycles materials
* Entity properties
* Lights
* Export arbitrary objects
* Per-object/face auto UV unwrap options - try to work similar to Radiant
* Much more...
