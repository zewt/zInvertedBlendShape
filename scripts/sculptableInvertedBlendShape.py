"""
Inverts a shape through the deformation chain

Based on https://github.com/chadmv/cvshapeinverter by Chad Vernon.
"""

import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import math, time

def _find_deformer_for_shape(node, node_type, future=False):
    """
    Find a node with the class node_type in node's history.
    """

    # The gl=True flag combined with pdo=True causes listHistory to only return the direct
    # history of this node, eg. it won't return blend shapes and the deformers of blend
    # shapes.
    for history_node in cmds.listHistory(node, gl=True, pdo=True, f=future) or []:
        if node_type in cmds.nodeType(history_node, inherited=True):
            return history_node

def _find_non_intermediate_output_mesh(node, first=True):
    """
    Return the first non-intermediate mesh in the future of the given node.

    For the deformer, this should be the inverted mesh.  The output of the blend
    shape is also in the future, but it comes later in the list.
    """
    history_nodes = cmds.listHistory(node, f=True)
    if not first:
        first = reversed(first)

    for history_node in history_nodes:
        if cmds.nodeType(history_node) != 'mesh':
            continue
        if cmds.getAttr('%s.intermediateObject' % history_node):
            continue
        return history_node

    raise RuntimeError('Couldn\'t find the output mesh for %s.' % node)

def _find_sculpting_output_mesh(deformer):
    """
    Find the mesh to sculpt on for deformer.
    """
    # Find the first visible, non-intermediate mesh in the future of the inverted mesh.
    #
    # Some more complex rigs may have more than one non-intermediate shape.  For example,
    # we may feed into a blend shape that feeds into a composed mesh, which itself is then
    # a blend shape for a higher-level mesh.  Try to pick the one the user wants to actually
    # sculpt on by paying attention to visibility, and not just intermediate.
    inverted_mesh = _find_non_intermediate_output_mesh(deformer)
    if inverted_mesh is None:
        OpenMaya.MGlobal.displayWarning('Couldn\'t find the inverted mesh for %s' % deformer)
        return None

    visible_nodes = []
    for history_node in cmds.listHistory(inverted_mesh, f=True):
        if history_node == inverted_mesh:
            continue
        if cmds.nodeType(history_node) != 'mesh':
            continue
        if not _node_visible(history_node):
            continue
        visible_nodes.append(history_node)

    if not visible_nodes:
        return None

    # If there's more than one visible mesh using this deformer, we might pick the wrong one.
    if len(visible_nodes) > 1:
        OpenMaya.MGlobal.displayWarning('More than one visible mesh uses %s.  Sculpting on: %s' % (deformer, visible_nodes[0]))
    return visible_nodes[0]

def _find_blend_shapes(node):
    # Look through history backwards, so front-of-chain blend shapes are found first.
    for history_node in reversed(cmds.listHistory(node, gl=True)):
        if 'blendShape' not in cmds.nodeType(history_node, inherited=True):
            continue

        # print 'Blend shape:', history_node, cmds.nodeType(history_node, inherited=True)
        yield history_node

def _find_visible_shape(transform):
    # If this is already a mesh, just use it.
    if cmds.nodeType(transform) == 'mesh':
        return transform

    shapes = cmds.listRelatives(transform, children=True, shapes=True) or []
    for s in shapes:
        if cmds.getAttr('%s.intermediateObject' % s):
            continue
        return s
    raise RuntimeError('No intermediate shape found for %s.' % transform)

def _find_first_blend_shape(node):
    blend_shapes = list(_find_blend_shapes(node))
    if len(blend_shapes) == 0:
        return

    return blend_shapes[0]

def _get_plug_from_node(node):
    selectionList = OpenMaya.MSelectionList()
    selectionList.add(node)
    plug = OpenMaya.MPlug()
    selectionList.getPlug(0, plug)
    return plug

def _get_shape(node):
    """
    Returns a shape node from a given transform or shape.
    """
    if cmds.nodeType(node) == 'transform':
        shapes = cmds.listRelatives(node, shapes=True, path=True)
        if not shapes:
            raise RuntimeError, '%s has no shape' % node
        return shapes[0]
    elif cmds.nodeType(node) in ['mesh', 'nurbsCurve', 'nurbsSurface']:
        return node

def _get_mobject(node):
    """
    Gets the dag path of a node.
    """
    selectionList = OpenMaya.MSelectionList()
    selectionList.add(node)
    oNode = OpenMaya.MObject()
    selectionList.getDependNode(0, oNode)
    return oNode

def _get_dag_path(node):
    """
    Gets the dag path of a node.
    """
    selectionList = OpenMaya.MSelectionList()
    selectionList.add(node)
    pathNode = OpenMaya.MDagPath()
    selectionList.getDagPath(0, pathNode)
    return pathNode

def _get_geometry_iterator(path):
    if isinstance(path, str) or isinstance(path, unicode):
        path = _get_dag_path(_get_shape(path))
    return OpenMaya.MItGeometry(path)

def _get_mesh_points(path, space=OpenMaya.MSpace.kObject):
    """
    Get the control point positions of a geometry node.
    """
    itGeo = _get_geometry_iterator(path)
    points = OpenMaya.MPointArray()
    itGeo.allPositions(points, space)
    return points

def _get_points(obj, space=OpenMaya.MSpace.kObject):
    itMesh = OpenMaya.MItMeshVertex(obj)

    # XXX: We should be able to stop iteration when next() returns an error, but that doesn't
    # actually happen in Python for some reason.
    result = OpenMaya.MPointArray()
    for idx in xrange(0, itMesh.count()):
        result.append(itMesh.position(space))
        itMesh.next()
        
    return result

def _set_matrix_row(matrix, newVector, row):
    """
    Sets a matrix row with an MVector or MPoint.
    """
    _set_matrix_cell(matrix, newVector.x, row, 0)
    _set_matrix_cell(matrix, newVector.y, row, 1)
    _set_matrix_cell(matrix, newVector.z, row, 2)


def _set_matrix_cell(matrix, value, row, column):
    """
    Set a matrix cell.
    """
    OpenMaya.MScriptUtil.setDoubleArray(matrix[row], column, value)

def _get_active_sculpting_mesh_for_deformer(deformer):
    """
    If sculpting is enabled on the deformer, return the output mesh.  Otherwise,
    return None.
    """
    # If sculpting is enabled, .tweak[0] will be connected to the .tweakLocation of
    # a mesh.
    connections = cmds.listConnections('%s.tweak[0]' % deformer, d=True, s=False) or []
    if len(connections) == 0:
        return None
    if len(connections) > 1:
        # This isn't expected.
        raise RuntimeError('More than one mesh points to %s.tweak[0]' % deformer)
    return connections[0]

#def find_plug_in_node(node, plugName):
#    depNode = OpenMaya.MFnDependencyNode(node)
#    plugs = depNode.findPlug(plugName)
#    return plugs.elementByLogicalIndex(0)

#def find_attr_plug_in_node(node, attrName):
#    depNode = OpenMaya.MFnDependencyNode(node)
#    attr_mobj = depNode.attribute(attrName)
#    return OpenMaya.MPlug(node, attr_mobj)

#def clean_duplicate(shapeNode, name=None):
#    shape = cmds.duplicate(shapeNode, name=name)[0]
#    cmds.delete(shape, ch=True)
#
#    # Delete the unnessary shapes
#    shapes = cmds.listRelatives(shape, children=True, shapes=True, path=True)
#    for s in shapes:
#        if cmds.getAttr('%s.intermediateObject' % s):
#            cmds.delete(s)
#
#    # Unlock the transformation attrs
#    for attr in 'trs':
#        for x in 'xyz':
#            cmds.setAttr('%s.%s%s' % (shape, attr, x), lock=False)
#    cmds.setAttr('%s.visibility' % shape, True)
#
#    return shape

def _add_blend_shape(blend_shape_node, base, target):
    """
    Add target as a blend shape on base, using the blendShape node blend_shape_node.

    Return the index of the new blend shape.
    """
    # Get the next free blend shape target index.  cmds.blendShape won't do this for us.
    existingIndexes = cmds.getAttr('%s.weight' % blend_shape_node, mi=True) or [-1]
    next_index = max(existingIndexes) + 1

    # Add the inverted shape to the blendShape.
    cmds.blendShape(blend_shape_node, edit=True,  t=(base, next_index, target, 1))

    # Return the target index.
    return next_index

def _find_inverted_shape_for_deformer(deformer):
    """
    Given a deformer, find the output inverted shape.
    """
    for node in cmds.listHistory(deformer, f=True):
        if node == deformer:
            continue
        if cmds.nodeType(node) == 'mesh':
            return node

        # We should always find the mesh before we hit a deformer.  This makes sure
        # that we don't go too far forward and start messing with the real mesh.
        if set(cmds.nodeType(node, inherited=True)) & {'geometryFilter', 'deformer'}:
            print 'Found deformer %s before the inverted mesh for deformer %s' % (node, deformer)
            return None

def _find_deformer(node):
    """
    Find a deformer from a node associated with it.
    """
    if cmds.nodeType(node) == 'transform':
        node = _find_visible_shape(node)

    # The node may be the deformer itself, the inverted blend shape mesh, or the output mesh
    # whose tweak node is attached to the deformer.
    if cmds.nodeType(node) == 'sculptableInvertedBlendShape':
        return node

    if cmds.nodeType(node) == 'mesh':
        # If the mesh's tweakLocation is connected to a sculptableInvertedBlendShape, we're updating the mesh
        # that's currently being sculpted.  This is the most common case.
        connections = cmds.listConnections('%s.tweakLocation' % node, s=True, d=False, t='sculptableInvertedBlendShape')
        if connections:
            return connections[0]

        # See if this is an output inverted blend shape mesh.
        deformer = _find_deformer_for_shape(node, 'sculptableInvertedBlendShape')
        if deformer:
            return deformer

    return None


def _update_inversion_for_deformer(deformer):
    # The deformer outputs to the inverted mesh, which then generally goes into a blendShape
    # and then a skinCluster to get the final mesh.  We need to figure out how changes to
    # the inverted mesh affect the final output mesh that the user is sculpting.
    #
    # First, we need to find the inverted mesh.  This is the first mesh in our future.
    # Note that the deformer could be plugged directly into the blendShape, but if this
    # is done, we have no mesh to modify to do this.
    #
    # Doing this instead of just looking at .outputGeometry avoids problems when Maya
    # silently adds helper nodes between us and the geometry, such as createColorSet.

    inverted_shape = _find_inverted_shape_for_deformer(deformer)
    if not inverted_shape:
        raise Exception('Couldn\'t find the output inverted mesh for "%s".' % deformer)

    # Get the mesh that's being sculpted.
    posed_mesh = _get_active_sculpting_mesh_for_deformer(deformer)
    if not posed_mesh:
        OpenMaya.MGlobal.displayError('Deformer "%s" isn\'t being sculpted.' % deformer)
        return

    # Temporarily disable the deformer.
    old_node_state = cmds.getAttr('%s.nodeState' % deformer)
    cmds.setAttr('%s.nodeState' % deformer, 1)

    # In 2016 SP1, auto-keyframe makes cmds.move extremely slow, so disable it while we
    # do this.
    old_autokeyframe = cmds.autoKeyframe(q=True, st=True)
    cmds.autoKeyframe(st=False)
    try:
        # We need to find out the effect that translating the blend shape vertices
        # has.  Do this by moving vertices on the actual blend shape.  We've disabled
        # the deformer while we test this.

        # The base shape data:
        basePoints = _get_mesh_points(posed_mesh)

        # The base shape after being deformed on each axis:
        cmds.move(1, 0, 0, '%s.vtx[*]' % inverted_shape, r=True, os=True)
        xPoints = _get_mesh_points(posed_mesh)
        cmds.move(-1, 0, 0, '%s.vtx[*]' % inverted_shape, r=True, os=True)

        cmds.move(0, 1, 0, '%s.vtx[*]' % inverted_shape, r=True, os=True)
        yPoints = _get_mesh_points(posed_mesh)
        cmds.move(0, -1, 0, '%s.vtx[*]' % inverted_shape, r=True, os=True)

        cmds.move(0, 0, 1, '%s.vtx[*]' % inverted_shape, r=True, os=True)
        zPoints = _get_mesh_points(posed_mesh)
        cmds.move(0, 0, -1, '%s.vtx[*]' % inverted_shape, r=True, os=True)

        # If moving points has no effect, something's wrong.  The blend shape may not
        # be enabled, or there could be another deformer in the way that's replacing
        # the shape entirely.
        if basePoints and abs(basePoints[0].x - xPoints[0].x) < 0.001:
            OpenMaya.MGlobal.displayError('Moving the inverted mesh isn\'t moving the output mesh.  Is the blend shape for this mesh enabled?')
            return
        
    finally:
        # Restore the deformer's state.
        cmds.setAttr('%s.nodeState' % deformer, old_node_state)

        # Restore autoKeyframe.
        cmds.autoKeyframe(st=old_autokeyframe)

    # Calculate the inversion matrices.
    deformer_node = _get_mobject(deformer)
    inversion_matrix_plug = OpenMaya.MFnDependencyNode(deformer_node).findPlug('inversionMatrix', False)
    fnMatrixData = OpenMaya.MFnMatrixData()

    for i in xrange(basePoints.length()):
        matrix = OpenMaya.MMatrix()
        _set_matrix_row(matrix, xPoints[i] - basePoints[i], 0)
        _set_matrix_row(matrix, yPoints[i] - basePoints[i], 1)
        _set_matrix_row(matrix, zPoints[i] - basePoints[i], 2)
        matrix = matrix.inverse()

        matrix_node = fnMatrixData.create(matrix)
        matrix_element_plug = inversion_matrix_plug.elementByLogicalIndex(i)
        matrix_element_plug.setMObject(matrix_node)

    # Now that we've updated the inversion, tell the deformer to recalculate the
    # .tweak values based on the .inverseTweak and the new .inversionMatrix.
    cmds.setAttr('%s.recalculateTweak' % deformer, 1)

def update_inversion(node=None):
    """
    Update the selected deformer's inversion, so it inverts the current pose.
    """
    if node is not None:
        nodes = [node]
    else:
        nodes = cmds.ls(sl=True)
        
    if not nodes:
        OpenMaya.MGlobal.displayError('Select a blend shape or output mesh')
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            deformer = _find_deformer(node)
            if deformer is None:
                OpenMaya.MGlobal.displayError('Couldn\'t find a sculptableInvertedBlendShape for: %s' % node)
                continue

            _update_inversion_for_deformer(deformer)

            OpenMaya.MGlobal.displayInfo('Updated the inversion for %s.' % deformer)
    finally:
        cmds.undoInfo(closeChunk=True)

def _load_plugin():
    if not cmds.pluginInfo('sculptableInvertedBlendShape.py', query=True, loaded=True):
        cmds.loadPlugin('sculptableInvertedBlendShape.py')

def invert(base=None, name=None):
    """
    Create an inverted blend shape for the selected mesh.

    The mesh must have a front-of-chain blendShape deformer.
    """
    _load_plugin()
    if not base:
        sel = cmds.ls(sl=True)
        if not sel or len(sel) != 1:
            OpenMaya.MGlobal.displayError('Select a mesh to create an inverted blend shape for.')
            return
        base = sel[0]

    # Find the front of chain blendShape node.
    foc_blend_shape = _find_first_blend_shape(base)
    # print 'Using blend shape node: %s' % foc_blend_shape
    if foc_blend_shape is None:
        OpenMaya.MGlobal.displayError('%s has no blendShape.' % base)
        return

    if not name:
        name = '%s_inverted' % base

    cmds.undoInfo(openChunk=True)
    try:
        # Create a new mesh to be the inverted shape.  The base mesh will be the same as the input
        # into the blend shape.
        blend_shape_input_geometry = _get_plug_from_node('%s.input[0].inputGeometry' % foc_blend_shape)
        inverted_shape_transform_node = OpenMaya.MFnMesh().copy(blend_shape_input_geometry.asMObject())
        inverted_shape_transform = OpenMaya.MFnTransform(inverted_shape_transform_node).partialPathName()

        # Important: The new mesh will have no shading group.  This looks like it works, but sculpting
        # tools will get confused and the mesh will randomly begin rendering corrupt in VP2.0 if we don't
        # assign a SG.
        cmds.sets(inverted_shape_transform, e=True, forceElement='initialShadingGroup')

        # Rename the new mesh's transform.
        inverted_shape_transform = cmds.rename(inverted_shape_transform, name)

        # Find the shape.
        inverted_shape = cmds.listRelatives(inverted_shape_transform, shapes=True, pa=True)[0]

        # print 'Shape node:', inverted_shape

        # Hide the new blend shape.
        cmds.setAttr('%s.visibility' % inverted_shape_transform, False)

        # Apply the same transform to the new shape as the input mesh.  This is just cosmetic,
        # since we only use the object space mesh.
        cmds.xform(inverted_shape_transform, ws=True, ro=cmds.xform(base, ws=True, ro=True, q=True))
        cmds.xform(inverted_shape_transform, ws=True, t=cmds.xform(base, ws=True, t=True, q=True))
        cmds.xform(inverted_shape_transform, ws=True, s=cmds.xform(base, ws=True, s=True, q=True))

        blend_shape_index = _add_blend_shape(foc_blend_shape, base, inverted_shape)

        # Enable our new blend shape.  It needs to be enabled for update_inversion to work,
        # and the user is probably about to edit the blend shape he just created.
        cmds.setAttr('%s.weight[%i]' % (foc_blend_shape, blend_shape_index), 1)

        # Create the deformer.
        deformer = cmds.deformer(inverted_shape, type='sculptableInvertedBlendShape')[0]

        # Hack: If we don't have at least one element in the array, compute() won't be called on it.
        cmds.setAttr('%s.invertedTweak[0]' % deformer, 0, 0, 0)

        # Perform the initial inversion.
        # Actually, we don't really need to do this, since we'll do it the first time the blend
        # shape is edited.  This only has an effect when modifying the tweaks.
        # _update_inversion_for_deformer(deformer)

        cmds.select(inverted_shape_transform)
        OpenMaya.MGlobal.displayInfo('Result: %s' % inverted_shape)
        return inverted_shape

    finally:
        cmds.undoInfo(closeChunk=True)

def invert_existing(inverted=None):
    """
    Create an inversion for an existing inverted blend shape.  Select the inverted
    blend shape, optionally followed by the final output shape.  If no output shape
    is selected, we'll guess the output shape to use.

    This can be used if you've deleted the blend shape deformer, or if you've
    recreated the blend shape mesh from a delta blend shape.
    """
    _load_plugin()

    cmds.undoInfo(openChunk=True)
    try:
        if not inverted:
            sel = cmds.ls(sl=True)
            if not sel or not len(sel):
                OpenMaya.MGlobal.displayError('Select an inverted mesh')
                return

            inverted = sel[0]

        inverted_shape = _find_visible_shape(inverted)
        if not inverted_shape:
            OpenMaya.MGlobal.displayError('Couldn\'t find a shape under %s' % inverted)

        print 'Shape: %s' % inverted_shape

        # There shouldn't already be sculptableInvertedBlendShape deformer on the mesh.
        for history_node in cmds.listHistory(inverted_shape):
            if 'sculptableInvertedBlendShape' in cmds.nodeType(history_node, inherited=True):
                OpenMaya.MGlobal.displayError('%s already has a sculptableInvertedBlendShape deformer (%s).' % (inverted, history_node))
                return

        # Find the blendShape that the mesh feeds into.
        for history_node in cmds.listHistory(inverted_shape, f=True):
            if 'blendShape' not in cmds.nodeType(history_node, inherited=True):
                continue

            foc_blend_shape = history_node
            break
        else:
            OpenMaya.MGlobal.displayError('%s has no blendShape.' % inverted_shape)
            return

        # Retrieve the current vertices for the inverted mesh.  Do this before we clobber it below.
        inverted_points = _get_mesh_points(inverted_shape)

        # Retrieve the input vertices coming into the blend shape.  These will become the input
        # into the deformer, and the deformer will apply the changes to get back to the inverted
        # mesh.
        blend_shape_input_geometry = _get_plug_from_node('%s.input[0].inputGeometry' % foc_blend_shape)
        blend_shape_input_points = _get_points(blend_shape_input_geometry.asMObject())
        if inverted_points.length() != blend_shape_input_points.length():
            raise RuntimeError('Expected %s and %s to have the same number of points' % (inverted_points, blend_shape_input_points))

        # Replace the input geometry (the input to the deformer) with the original geometry
        # coming into the blend shape.  The inverted shape will be applied by the deformer.
        inverted_points_iterator = _get_geometry_iterator(inverted_shape)
        inverted_points_iterator.setAllPositions(blend_shape_input_points, OpenMaya.MSpace.kObject)

        # Find this mesh's blend shape index.
        # XXX: How to do this?  There might be other deformers like createColorSet between
        # us and the blend shape, and the attribute hierarchy for blendShape is fairly complex.
        # We can use listHistory to find the node just before the blendShape and between
        # it and us, but that won't tell us which plug it's connected to the blendShape with.
        # List them all?
        # blend_shape_index = _add_blend_shape(foc_blend_shape, base, inverted_shape)
        #
        # Enable the blend shape.  If the blend shape isn't enabled, update_inversion won't be
        # able to figure out how changes to the blend shape affect the output mesh.
        # cmds.setAttr('%s.weight[%i]' % (foc_blend_shape, blend_shape_index), 1)

        # Create the deformer.
        deformer = cmds.deformer(inverted_shape, type='sculptableInvertedBlendShape')[0]

        # Hack: If we don't have at least one element in the array, compute() won't be called on it.
        cmds.setAttr('%s.invertedTweak[0]' % deformer, 0, 0, 0)
                   
        # Create .invertedTweak from the inverted mesh and the original mesh.
        values = []
        for i in xrange(inverted_points.length()):
            delta = inverted_points[i] - blend_shape_input_points[i]
            values.append((delta.x, delta.y, delta.z))

        # XXX: This is slow.
        for idx, value in enumerate(values):
            cmds.setAttr('%s.invertedTweak[%i]' % (deformer, idx), *value)

        # Set up .inversionMatrix.
        _update_inversion_for_deformer(deformer)
            
        OpenMaya.MGlobal.displayInfo('Result: %s' % deformer)
        return deformer

    finally:
        cmds.undoInfo(closeChunk=True)

def _node_visible(node):
    """
    Return true if node is visible.

    Is there a standard way to do this?
    """
    if not cmds.attributeQuery('visibility', node=node, exists=True):
        return False

    if not cmds.getAttr('%s.visibility' % node):
        return False
    if cmds.getAttr('%s.intermediateObject' % node):
        return False

    # Display layers:
    if cmds.attributeQuery('overrideEnabled', node=node, exists=True) and cmds.getAttr('%s.overrideEnabled' % node):
        if not cmds.getAttr('%s.overrideVisibility' % node):
            return False

    parents = cmds.listRelatives(node, parent=True) or []
    if parents:
        return _node_visible(parents[0])

    return True


def _enable_editing_for_deformer(deformer):
    posed_mesh =  _find_sculpting_output_mesh(deformer)
    if not posed_mesh:
        OpenMaya.MGlobal.displayError('Couldn\'t find a visible output mesh for %s to sculpt on' % deformer)
        return False

    # You have to have the blend shape selected to select which one to edit, but you most likely
    # want to actually edit the shape now, so select the transform for the output mesh.  In the
    # unlikely case that there are multiple instances, we'll just pick one.  Do this even if the
    # blend shape is already selected for editing.
    posed_mesh_transform = cmds.listRelatives(posed_mesh, p=True)
    cmds.select(posed_mesh_transform[0])

    # If something is already connected to our tweak input, we're already enabled.
    if _get_active_sculpting_mesh_for_deformer(deformer):
        OpenMaya.MGlobal.displayWarning('%s is already enabled for editing' % deformer)
        return True

    # We're going to connect the deformer to posedMesh's tweakLocation, but we need to
    # be able to undo this when disabling editing again.  The blend shape UI does this
    # without saving it, figuring out if there's a tweak node that it should be connected
    # to, but I'm not sure of the logic to do that.  To be safe, just save the original
    # connection.
    #
    # Note that there may be no existing tweak connection.
    existing_connections = cmds.listConnections('%s.tweakLocation' % posed_mesh, p=True)
    if existing_connections:
        print 'Saving existing connection %s' % existing_connections[0]
        cmds.connectAttr(existing_connections[0], '%s.savedTweakConnection[0]' % deformer, f=True)
    
    # Now connect our tweak attribute to the mesh's tweakLocation, overwriting any existing connection.
    existing_connections = cmds.listConnections('%s.savedTweakConnection' % deformer)
    cmds.connectAttr('%s.tweak[0]' % deformer, '%s.tweakLocation' % posed_mesh, f=True)

    # Make sure the inversion is up to date.
    _update_inversion_for_deformer(deformer)

    return True

def enable_editing(node=None):
    """
    Enable editing an inverted blend shape.

    The inversion matrices will also be updated.
    """
    if node is not None:
        nodes = [node]
    else:
        nodes = cmds.ls(sl=True)
        
    if not nodes:
        OpenMaya.MGlobal.displayError('Select an inverted blend shape')
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            # We can select a deformer or an inverted shape node.  We can't select the
            # final output shape, since we won't know which blend shape to enable.
            deformer = _find_deformer(node)
            if deformer is None:
                OpenMaya.MGlobal.displayError('Couldn\'t find a sculptableInvertedBlendShape for: %s' % node)
                continue

            if _enable_editing_for_deformer(deformer):
                msg = 'Editing <hl>enabled</hl> fo: %s' % node
                cmds.inViewMessage(smg=msg, pos='botCenter', fade=1)
    finally:
        cmds.undoInfo(closeChunk=True)

def _disable_editing_for_deformer(deformer):
    # Select the inverted blend shape, so we're symmetrical with what enable_editing does.
    # That way, enable_editing and disable_editing toggles back and forth cleanly.
    inverted_mesh_shape = _find_non_intermediate_output_mesh('%s.outputGeometry[0]' % deformer)
    inverted_mesh = cmds.listRelatives(inverted_mesh_shape, p=True)[0]
    cmds.select(inverted_mesh)
    
    posed_mesh = _get_active_sculpting_mesh_for_deformer(deformer)
    if not posed_mesh:
        OpenMaya.MGlobal.displayWarning('%s isn\'t enabled for editing' % deformer)

        # Don't show the "disabled editing" message, so it doesn't imply that it was
        # actually enabled before.
        return False

    # .tweak[0] is connected to posed_mesh's .tweakLocation.  Disconnect this connection.
    cmds.disconnectAttr('%s.tweak[0]' % deformer, '%s.tweakLocation' % posed_mesh)

    # If we have a .savedTweakConnection, connect posed_mesh's .tweakLocation back to it.
    saved_tweak_connection = cmds.listConnections('%s.savedTweakConnection[0]' % deformer, p=True)
    if saved_tweak_connection:
        print 'Restoring', saved_tweak_connection
        saved_tweak_connection = saved_tweak_connection[0]
        cmds.connectAttr(saved_tweak_connection, '%s.tweakLocation' % posed_mesh)
        cmds.disconnectAttr(saved_tweak_connection, '%s.savedTweakConnection[0]' % deformer)

    return True

def disable_editing(node=None):
    """
    Disable editing an inverted blend shape.
    """
    if node is not None:
        nodes = [node]
    else:
        nodes = cmds.ls(sl=True)
        
    if not nodes:
        OpenMaya.MGlobal.displayError('Select an inverted blend shape')
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            # We can select a deformer or an inverted shape node.  We can't select the
            # final output shape, since we won't know which blend shape to enable.
            deformer = _find_deformer(node)
            if deformer is None:
                OpenMaya.MGlobal.displayError('Couldn\'t find a sculptableInvertedBlendShape for: %s' % node)
                continue

            if _disable_editing_for_deformer(deformer):
                msg = 'Editing <hl>disabled</hl> for: %s' % node
                cmds.inViewMessage(smg=msg, pos='botCenter', fade=1)
    finally:
        cmds.undoInfo(closeChunk=True)


