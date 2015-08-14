This Maya plug-in allows creating inverted blend shapes that can be sculpted
in-place, like Maya 2016's blend shape sculpting.

This is based on Chad Vernon's cvShapeInverter: https://github.com/chadmv/cvshapeinverter

Installation
------------

Install by copying zInvertedBlendShape.mod into Maya's modules
directory and setting the correct path, and adding this to your userSetup.mel:

```
source "zInvertedBlendShapeMenu.mel";
```

An "Inverted Blend Shape" menu will be added to the Deform menu in the Rigging menu set.

Creating and editing blend shapes
---------------------------------

To create an inverted blend shape, first create a front-of-chain blend shape
deformer on your mesh.  Select your mesh, and select **Inverted Blend Shape > Deform**.
This will create an inverted shape and hook it up to the front-of-chain
blend shape deformer.  To sculpt the blend shape, select the new shape and
select **Enable editing**.  This command works like selecting "edit" in
the blend shape dialog.  Be sure that the output mesh is selected when
sculpting.  The blend shape node can remain hidden.

If you change the character's pose while editing, the blend shape will
continue to work.  However, if you want to make further changes after
changing the pose, you need to tell the deformer about this by selecting
**Update pose**.  If you're editing the shape and vertices are moving in
the wrong direction, you probably need to do this.

Deleting and recreating the deformer
------------------------------------

You can delete history on the blend shape mesh to remove the inversion
node, which will bake the inversion to the mesh.  This can be done
if you don't want your scene to require this plugin to be available.

To recreate the inversion node to make further edits, or to edit an
existing inverted blend shape, select the blend shape mesh and select
**Add deformer**.

You can also simply delete the whole blend shape when you're done, and the
blend shape will be baked into the blend shape deformer as deltas.

