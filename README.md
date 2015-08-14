This is based on Chad Vernon's cvShapeInverter: https://github.com/chadmv/cvshapeinverter

That plugin creates an inverted shape that can be used as a blend shape,
but it's not compatible with Maya 2016's in-place blend shape sculpting.
This means that you need to have separate inverted and uninverted meshes,
sculpt the uninverted mesh, and you can't change the pose when editing.

Installation
------------

Install by copying invertedBlendShape.mod into Maya's modules
directory and setting the correct path, and adding this to your userSetup.mel:

```
source "zInvertedBlendShapeMenu.mel";
```

An "Inverted Blend Shape" menu will be added to the rigging Deform menu.

Creating and editing blend shapes
---------------------------------

To create an inverted blend shape, first create a front-of-chain blend shape
deformer on your mesh.  Select your mesh, and select *Deform*.
This will create an inverted shape and hook it up to the front-of-chain
blend shape deformer.  To sculpt the deformer, select the new shape and
select *Enable editing*.  These two commands work like selecting "edit" in
the blend shape dialog.  Be sure that the output mesh is selected when
sculpting.  The blend shape node can remain hidden.

If you change the character's pose while editing, the blend shape will
continue to work.  However, if you want to make further changes after
changing the pose, you need to tell the deformer about this by selecting
*Update pose*.  If you're editing the shape and vertices are moving in
the wrong direction, you probably need to do this.

Deleting and recreating the deformer
------------------------------------

You can delete history on the blend shape mesh to remove this inversion
node, which will bake the inversion down on the mesh.  You can do this
if you don't want your scene to require this plugin to be loaded.

If you want to recreate the inversion node to make further edits, or if
you want to edit an existing inverted blend shape, select the blend shape
mesh and select *Add deformer*.

You can also simply delete the whole blend shape when you're done, and the
blend shape will be baked into the blend shape deformer as deltas.

