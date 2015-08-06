"""
Inverts a shape through the deformation chain

Based on https://github.com/chadmv/cvshapeinverter by Chad Vernon.
"""

import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import math

def _find_blend_shapes(node):
    # Look through history backwards, so front-of-chain blend shapes are found first.
    for historyNode in reversed(cmds.listHistory(node)):
        if 'blendShape' not in cmds.nodeType(historyNode, inherited=True):
            continue

        # print 'Blend shape:', historyNode, cmds.nodeType(historyNode, inherited=True)
        yield historyNode

def _find_visible_shape(transform):
    shapes = cmds.listRelatives(transform, children=True, shapes=True)
    for s in shapes:
        if cmds.getAttr('%s.intermediateObject' % s):
            continue
        return s
    raise RuntimeError('No intermediate shape found for %s.' % base)

def _find_first_blend_shape(node):
    blend_shapes = list(_find_blend_shapes(node))
    if len(blend_shapes) == 0:
        return

    first_blend_shape = blend_shapes[0]
    print 'Using blend shape node: %s' % first_blend_shape
    return first_blend_shape

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

def _get_mesh_points(path, space=OpenMaya.MSpace.kObject):
    """
    Get the control point positions of a geometry node.
    """
    if isinstance(path, str) or isinstance(path, unicode):
        path = _get_dag_path(_get_shape(path))
    itGeo = OpenMaya.MItGeometry(path)
    points = OpenMaya.MPointArray()
    itGeo.allPositions(points, space)
    return points

#def _get_points(plug, space=OpenMaya.MSpace.kObject):
#    itMesh = OpenMaya.MItMeshVertex(plug.asMObject())
#
#    # XXX: We should be able to stop iteration when next() returns an error, but that doesn't
#    # actually happen in Python for some reason.
#    result = OpenMaya.MPointArray()
#    for idx in xrange(0, itMesh.count()):
#        result.append(itMesh.position(space))
#        itMesh.next()
#        
#    print result.length()
#    return result

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

def _add_blend_shape(blendShapeNode, base, target):
    # Get the next free blend shape target index.  cmds.blendShape won't do this for us.
    existingIndexes = cmds.getAttr('%s.weight' % blendShapeNode, mi=True) or [-1]
    nextIndex = max(existingIndexes) + 1

    # Add the inverted shape to the blendShape.
    cmds.blendShape(blendShapeNode, edit=True,  t=(base, nextIndex, target, 1))

    # Return the target index.
    return nextIndex

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
    if cmds.nodeType(node) == 'testDeformer':
        return node

    if cmds.nodeType(node) == 'mesh':
        # If the mesh's tweakLocation is connected to a testDeformer, we're updating the mesh
        # that's currently being sculpted.  This is the most common case.
        connections = cmds.listConnections('%s.tweakLocation' % node, s=True, d=False, t='testDeformer')
        if connections:
            return connections[0]

        # See if this is an output inverted blend shape mesh.
        connections = cmds.listConnections('%s.inMesh' % node, s=True, d=False, t='testDeformer')
        if connections:
            return connections[0]

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

    # The posedMesh connection points to the mesh that's being sculpted.  This is the original
    # mesh that was selected when the deformer was created.
    posed_mesh = cmds.listConnections('%s.posedMesh' % deformer, sh=True)
    if not posed_mesh:
        print 'Deformer "%s" has no posedMesh connection.' % deformer
        return
    posed_mesh = posed_mesh[0]

    # Temporarily disable the deformer.
    try:
        old_node_state = cmds.getAttr('testDeformer1.nodeState')
        cmds.setAttr('testDeformer1.nodeState', 1)

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
    finally:
        # Restore the deformer's state.
        cmds.setAttr('testDeformer1.nodeState', old_node_state)

    # Calculate the inversion matrices.
    oDeformer = _get_mobject(deformer)
    fnDeformer = OpenMaya.MFnDependencyNode(oDeformer)
    plugMatrix = fnDeformer.findPlug('inversionMatrix', False)
    fnMatrixData = OpenMaya.MFnMatrixData()

    for i in xrange(basePoints.length()):
        matrix = OpenMaya.MMatrix()
        _set_matrix_row(matrix, xPoints[i] - basePoints[i], 0)
        _set_matrix_row(matrix, yPoints[i] - basePoints[i], 1)
        _set_matrix_row(matrix, zPoints[i] - basePoints[i], 2)

        matrix = matrix.inverse()
        oMatrix = fnMatrixData.create(matrix)

        plugMatrixElement = plugMatrix.elementByLogicalIndex(i)
        plugMatrixElement.setMObject(oMatrix)

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
        print 'Select a blend shape or output mesh'
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            deformer = _find_deformer(node)
            if deformer is None:
                print 'Couldn\'t find a testDeformer for: %s' % node
                continue

            _update_inversion_for_deformer(deformer)
    finally:
        cmds.undoInfo(closeChunk=True)

def invert(base=None, name=None):
    """
    Create an inverted blend shape for the selected mesh.

    The mesh must have a front-of-chain blendShape deformer.
    """
    if not cmds.pluginInfo('sculptableInvertedBlendShape.py', query=True, loaded=True):
        cmds.loadPlugin('sculptableInvertedBlendShape.py')
    if not base:
        sel = cmds.ls(sl=True)
        if not sel or len(sel) != 1:
            print 'Select a mesh'
            return
        base = sel[0]

    if not name:
        name = '%s_inverted' % base

    cmds.undoInfo(openChunk=True)
    try:
        base_shape = _find_visible_shape(base)
        # print 'Base shape:', base_shape

        # Find the front of chain blendShape node.
        foc_blend_shape = _find_first_blend_shape(base)
        if foc_blend_shape is None:
            print '%s has no blendShape.' % base
            return

        # Create a new mesh to be the inverted shape.  Doing it this way instead of duplicating the
        # input mesh avoids mesh tweaks (mesh.vt[*]) from being copied in, which can cause the new
        # mesh to not be the same as the input to the blendShape.
        inverted_shape = cmds.createNode('mesh', name='%sShape' % name)

        # Rename the new mesh's transform.
        inverted_shape_transform = cmds.listRelatives(inverted_shape, parent=True, pa=True)[0]
        inverted_shape_transform = cmds.rename(inverted_shape_transform, name)

        # Renaming the transform may have automatically renamed the shape.
        inverted_shape = cmds.listRelatives(inverted_shape_transform, shapes=True, pa=True)[0]

        # print 'Shape node:', inverted_shape

        # Hide the new blend shape.
        cmds.setAttr('%s.visibility' % inverted_shape_transform, False)

        # Apply the same transform to the new shape as the input mesh.  This is just cosmetic,
        # since we only use the object space mesh.
        cmds.xform(inverted_shape, ws=True, ro=cmds.xform(base, ws=True, ro=True, q=True))
        cmds.xform(inverted_shape, ws=True, t=cmds.xform(base, ws=True, t=True, q=True))
        cmds.xform(inverted_shape, ws=True, s=cmds.xform(base, ws=True, s=True, q=True))

        blend_shape_input_geometry = _get_plug_from_node('%s.input[0].inputGeometry' % foc_blend_shape)

        # Connect the input of the blendShape to the input of the new mesh.
        inverted_shape_in_mesh_plug = _get_plug_from_node('%s.inMesh' % inverted_shape)
        modifier = OpenMaya.MDGModifier()
        modifier.connect(blend_shape_input_geometry, inverted_shape_in_mesh_plug)
        modifier.doIt()

        # Read the shape to force it to update, or it'll still be in its original position
        # after we disconnect below.
        _get_mesh_points(inverted_shape)

        # Immediately disconnect it again.  We're just doing this to copy the input data of the
        # blend shape to the new shape.
        modifier = OpenMaya.MDGModifier()
        modifier.disconnect(blend_shape_input_geometry, inverted_shape_in_mesh_plug)
        modifier.doIt()

        blend_shape_index = _add_blend_shape(foc_blend_shape, base, inverted_shape)

        # Enable our new blend shape.
        cmds.setAttr('%s.weight[%i]' % (foc_blend_shape, blend_shape_index), 1)

        # Create the deformer.
        deformer = cmds.deformer(inverted_shape, type='testDeformer')[0]

        # Hack: If we don't have at least one element in the array, compute() won't be called on it.
        cmds.setAttr('%s.invertedTweak[0]' % deformer, 0, 0, 0)

        # Remember the base shape, so we can find it later.
        cmds.connectAttr('%s.outMesh' % base_shape, '%s.posedMesh' % deformer)

        update_inversion(deformer)

        cmds.select(inverted_shape_transform)
        return inverted_shape

    finally:
        cmds.undoInfo(closeChunk=True)

def _enable_editing_for_deformer(deformer):
    # If something is already connected to our tweak input, we're already enabled.
    if cmds.listConnections('%s.tweak[0]' % deformer, s=False, d=True):
        print '%s is already enabled for editing' % deformer
        return

    posed_mesh = cmds.listConnections('%s.posedMesh' % deformer, sh=True)
    if not posed_mesh:
        print 'Deformer "%s" has no posedMesh connection.' % deformer
        return
    posed_mesh = posed_mesh[0]

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

    msg = 'Editing <hl>enabled</hl> for blend shape target: %s' % deformer
    cmds.inViewMessage(smg=msg, pos='botCenter', fade=1)

def enable_editing(node=None):
    """
    Enable editing an inverted blend shape.
    """
    if node is not None:
        nodes = [node]
    else:
        nodes = cmds.ls(sl=True)
        
    if not nodes:
        print 'Select a blend shape'
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            # We can select a deformer or an inverted shape node.  We can't select the
            # final output shape, since we won't know which blend shape to enable.
            deformer = _find_deformer(node)
            if deformer is None:
                print 'Couldn\'t find a testDeformer for: %s' % node
                continue

            _enable_editing_for_deformer(deformer)
    finally:
        cmds.undoInfo(closeChunk=True)

def _disable_editing_for_deformer(deformer):
    if not cmds.listConnections('%s.tweak[0]' % deformer, s=False, d=True):
        print '%s isn\'t enabled for editing' % deformer
        return

    posed_mesh = cmds.listConnections('%s.posedMesh' % deformer, sh=True)
    if not posed_mesh:
        print 'Deformer "%s" has no posedMesh connection.' % deformer
        return
    posed_mesh = posed_mesh[0]

    # .tweak[0] is connected to .posedMesh's .tweakLocation.  Disconnect this connection.
    cmds.disconnectAttr('%s.tweak[0]' % deformer, '%s.tweakLocation' % posed_mesh)

    # If we have a .savedTweakConnection, connect .posedMesh's .tweakLocation back to it.
    saved_tweak_connection = cmds.listConnections('%s.savedTweakConnection[0]' % deformer, p=True)
    if saved_tweak_connection:
        print 'Restoring', saved_tweak_connection
        saved_tweak_connection = saved_tweak_connection[0]
        cmds.connectAttr(saved_tweak_connection, '%s.tweakLocation' % posed_mesh)
        cmds.disconnectAttr(saved_tweak_connection, '%s.savedTweakConnection[0]' % deformer)

    msg = 'Editing <hl>disabled</hl> for blend shape target: %s' % deformer
    cmds.inViewMessage(smg=msg, pos='botCenter', fade=1)

def disable_editing(node=None):
    """
    Disable editing an inverted blend shape.
    """
    if node is not None:
        nodes = [node]
    else:
        nodes = cmds.ls(sl=True)
        
    if not nodes:
        print 'Select a blend shape'
        return

    cmds.undoInfo(openChunk=True)
    try:
        for node in nodes:
            # We can select a deformer or an inverted shape node.  We can't select the
            # final output shape, since we won't know which blend shape to enable.
            deformer = _find_deformer(node)
            if deformer is None:
                print 'Couldn\'t find a testDeformer for: %s' % node
                continue

            _disable_editing_for_deformer(deformer)
    finally:
        cmds.undoInfo(closeChunk=True)


