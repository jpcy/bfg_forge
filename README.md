# BFG Forge
https://github.com/jpcy/bfg_forge

A Blender addon for [RBDOOM-3-BFG](https://github.com/RobertBeckebans/RBDOOM-3-BFG) mapping.

Based on [Level Buddy by Matt Lucas](https://matt-lucas.itch.io/level-buddy)

[![screenshot](http://i.imgur.com/gPzqGYU.jpg)](http://i.imgur.com/yf6es1x.jpg)

### Usage
* Extract the Doom 3 BFG resource files by running `exec extract_resources.cfg` from the RBDOOM-3-BFG console.
* Set the path in BFG Forge settings.
* Import materials and entities.

Unfortunately, BFG Forge can't read the extracted Doom 3 BFG textures, and the qer_editorimage textures are missing. You can substitute them with vanilla Doom 3 textures by extracting the pk4 files. Otherwise, uncheck "Hide bad materials" in BFG Forge settings to show materials with missing textures.

### Features/Progress
* Basic material decl and entity def parsing
* Selectable material decl with preview image and icons
* Create material from decl
* Create entities, set properties
* Create lights, set properties - partially done
* Create static models / func_static - partially done
* Use Level Buddy for quickly building a mesh - similar to subtractive and additive brushes
* Use Texture Buddy for simple automatic UV unwrap
* Map file exporter

### Known problems
* Various issues with Carve - the library Blender uses internally for boolean operations - failing. Intersect rooms slightly as a workaround.
* Blender doesn't display large numbers of EnumProperty values correctly, such as textures/base_wall material decl thumbnails.
