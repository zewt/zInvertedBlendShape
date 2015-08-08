This is based on Chad Vernon's cvShapeInverter: https://github.com/chadmv/cvshapeinverter

That plugin creates an inverted shape that can be used as a blend shape,
but it's not compatible with Maya 2016's in-place blend shape sculpting.
This means that you need to have separate inverted and uninverted meshes,
sculpt the uninverted mesh, and you can't change the pose when editing.

To create an inverted blend shape, first create a front-of-chain blend shape
deformer on your mesh.  Then, select your mesh and run:

import sculptableInvertedBlendShape
sculptableInvertedBlendShape.invert()

This will create an inverted shape and hook it up to the front-of-chain
blend shape deformer.  To sculpt the deformer, select the new shape and run:

sculptableInvertedBlendShape.enable_editing()

You can now sculpt your mesh in-place.  When you're done, disable editing:

sculptableInvertedBlendShape.disable_editing()

These two commands work like selecting "edit" in the blend shape dialog.

If you change the character's pose while editing, the blend shape will
continue to work.  However, if you want to make further changes after
changing the pose, you need to tell the deformer about this:

sculptableInvertedBlendShape.update_inversion()

If you're editing the shape and vertices are moving in the wrong direction,
you probably need to do this.

Finally, you can simply delete the inverted mesh when you're done, and
the blend shape will be baked into the blend shape deformer.

