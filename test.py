"""@brief Inverts a shape through the deformation chain
@author Chad Vernon - chadvernon@gmail.com - www.chadvernon.com
"""

import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import math

def find_blend_shapes(node):
    print 'All history:', list(reversed(cmds.listHistory(node)))
    # Look through history backwards, so front-of-chain blend shapes are found first.
    for historyNode in reversed(cmds.listHistory(node)):
        if 'blendShape' not in cmds.nodeType(historyNode, inherited=True):
            continue

        print 'Blend shape:', historyNode, cmds.nodeType(historyNode, inherited=True)
        yield historyNode

def find_visible_shape(transform):
    shapes = cmds.listRelatives(transform, children=True, shapes=True)
    for s in shapes:
        if cmds.getAttr('%s.intermediateObject' % s):
            continue
        return s
    raise RuntimeError('No intermediate shape found for %s.' % base)

def find_foc_blend_shape(node):
    blend_shapes = list(find_blend_shapes(node))
    if len(blend_shapes) == 0:
        print 'No blend shapes found on %s' % node
        return
    first_blend_shape = blend_shapes[0]
    print 'Using blend shape node: %s' % first_blend_shape
    return first_blend_shape

def get_plug_from_node(node):
    selectionList = OpenMaya.MSelectionList()
    selectionList.add(node)
    plug = OpenMaya.MPlug()
    selectionList.getPlug(0, plug)
    return plug

def find_plug_in_node(node, plugName):
    depNode = OpenMaya.MFnDependencyNode(node)
    plugs = depNode.findPlug(plugName)
    return plugs.elementByLogicalIndex(0)

def find_attr_plug_in_node(node, attrName):
    depNode = OpenMaya.MFnDependencyNode(node)
    attr_mobj = depNode.attribute(attrName)
    return OpenMaya.MPlug(node, attr_mobj)

def clean_duplicate(shapeNode, name=None):
    shape = cmds.duplicate(shapeNode, name=name)[0]
    cmds.delete(shape, ch=True)

    # Delete the unnessary shapes
    shapes = cmds.listRelatives(shape, children=True, shapes=True, path=True)
    for s in shapes:
        if cmds.getAttr('%s.intermediateObject' % s):
            cmds.delete(s)

    # Unlock the transformation attrs
    for attr in 'trs':
        for x in 'xyz':
            cmds.setAttr('%s.%s%s' % (shape, attr, x), lock=False)
    cmds.setAttr('%s.visibility' % shape, True)


    return shape

def addBlendShape(blendShapeNode, base, target):
    # Get the next free blend shape target index.  cmds.blendShape won't do this for us.
    existingIndexes = cmds.getAttr('%s.weight' % blendShapeNode, mi=True) or [-1]
    nextIndex = max(existingIndexes) + 1

    # Add the inverted shape to the blendShape.
    cmds.blendShape(blendShapeNode, edit=True,  t=(base, nextIndex, target, 1));

    # Return the target index.
    return nextIndex

def updateInversion(deformer):
    """
    Update the deformer's inversion, so it inverts the current pose.
    """
    cmds.undoInfo(openChunk=True)
    try:
        posedMesh = cmds.listConnections('%s.posedMesh' % deformer, sh=True)

        if not posedMesh:
            print 'Deformer "%s" has no posedMesh connection.' % deformer
            return
        posedMesh = posedMesh[0]

        invertedShape = cmds.listConnections('%s.outputGeometry[0]' % deformer, sh=True)
        if not invertedShape:
            print 'Deformer "%s" has no output connection.' % deformer
            return
        invertedShape = invertedShape[0]

        # Temporarily disable the deformer.
        oldNodeState = cmds.getAttr('testDeformer1.nodeState')
        cmds.setAttr('testDeformer1.nodeState', 1)

        # We need to find out the effect that translating the blend shape vertices
        # has.  Do this by moving vertices on the actual blend shape.  We've disabled
        # the deformer while we test this.

        # The base shape data:
        basePoints = getMeshPoints(posedMesh)

        # The base shape after being deformed on each axis:
        cmds.move(1, 0, 0, '%s.vtx[*]' % invertedShape, r=True, os=True)
        xPoints = getMeshPoints(posedMesh)
        cmds.move(-1, 0, 0, '%s.vtx[*]' % invertedShape, r=True, os=True)

        cmds.move(0, 1, 0, '%s.vtx[*]' % invertedShape, r=True, os=True)
        yPoints = getMeshPoints(posedMesh)
        cmds.move(0, -1, 0, '%s.vtx[*]' % invertedShape, r=True, os=True)

        cmds.move(0, 0, 1, '%s.vtx[*]' % invertedShape, r=True, os=True)
        zPoints = getMeshPoints(posedMesh)
        cmds.move(0, 0, -1, '%s.vtx[*]' % invertedShape, r=True, os=True)

        # Reenable the deformer (or put it back in its old state).
        cmds.setAttr('testDeformer1.nodeState', oldNodeState)

        # Calculate the inversion matrices
        oDeformer = getMObject(deformer)
        fnDeformer = OpenMaya.MFnDependencyNode(oDeformer)
        plugMatrix = fnDeformer.findPlug('inversionMatrix', False)
        fnMatrixData = OpenMaya.MFnMatrixData()

        for i in xrange(basePoints.length()):
            matrix = OpenMaya.MMatrix()
            setMatrixRow(matrix, xPoints[i] - basePoints[i], 0)
            setMatrixRow(matrix, yPoints[i] - basePoints[i], 1)
            setMatrixRow(matrix, zPoints[i] - basePoints[i], 2)

            matrix = matrix.inverse()
            oMatrix = fnMatrixData.create(matrix)

            plugMatrixElement = plugMatrix.elementByLogicalIndex(i)
            plugMatrixElement.setMObject(oMatrix)

        # Now that we've updated the inversion, tell the deformer to recalculate the
        # .tweak values based on the .inverseTweak and the new .inversionMatrix.
        cmds.setAttr('%s.recalculateTweak' % deformer, 1)
    finally:
        cmds.undoInfo(closeChunk=True)

def invert(base=None, name=None):
    """@brief Inverts a shape through the deformation chain.

    @param[in] base Deformed base mesh.
    @param[in] corrective Sculpted corrective mesh.
    @param[in] name Name of the generated inverted shape.
    @return The name of the inverted shape.
    """
#    if not cmds.pluginInfo('cvShapeInverter.py', query=True, loaded=True):
#        cmds.loadPlugin('cvShapeInverter.py')
    if not base:
        sel = cmds.ls(sl=True)
        if not sel or len(sel) != 1:
            raise RuntimeError, 'Select mesh'
        base = sel

    if not name:
        name = '%s_inverted' % base

    corrective = '%s_corrective' % base

    cmds.undoInfo(openChunk=True)
    try:
        base_shape = find_visible_shape(base)
        print 'Base shape:', base_shape

        # Find the front of chain blendShape node.
        foc_blend_shape = find_foc_blend_shape(base)
        if foc_blend_shape is None:
            raise RuntimeError, '%s has no blendShape' % base

        # Duplicate the base.  This will be the inverted shape.
        # XXX: The only reason we're copying this shape is to preserve transforms.  All of the
        # shape data is being deleted or overwritten.  This could probably be simplified.
        invertedShape = clean_duplicate(base, name=name)
        cmds.setAttr('%s.visibility' % invertedShape, False)

        blend_shape_index = addBlendShape(foc_blend_shape, base, invertedShape)


        blend_shape_input_geometry = get_plug_from_node('%s.input[0].inputGeometry' % foc_blend_shape)



        inverted_shape_shape_node = find_visible_shape(invertedShape)
        print 'Shape node:', inverted_shape_shape_node

        # Connect the input of the blendShape to the input of the new mesh.
        inverted_shape_in_mesh_plug = get_plug_from_node('%s.inMesh' % inverted_shape_shape_node)
        modifier = OpenMaya.MDGModifier()
        modifier.connect(blend_shape_input_geometry, inverted_shape_in_mesh_plug)
        modifier.doIt()

        # Read the shape to force it to update, or it'll still be in its original position
        # after we disconnect below.
        getMeshPoints(inverted_shape_shape_node)

        # Immediately disconnect it again.  We're just doing this to copy the input data of the
        # blend shape to the new shape.
        modifier = OpenMaya.MDGModifier()
        modifier.disconnect(blend_shape_input_geometry, inverted_shape_in_mesh_plug)
        modifier.doIt()

        # Enable our new blend shape.
        cmds.setAttr('%s.weight[%i]' % (foc_blend_shape, blend_shape_index), 1)

        # Create the deformer.
        # XXX: We should connect this to the base shape, not a copy
        # Maybe this shouldn't really be a deformer and just an MPxNode
        deformer = cmds.deformer(invertedShape, type='testDeformer')[0]

        # Hack: If we don't have at least one element in the array, compute() won't be called on it.
        cmds.setAttr('%s.invertedTweak[0]' % deformer, 0, 0, 0)

        # Remember the base shape, so we can find it later.
        cmds.connectAttr('%s.outMesh' % base_shape, '%s.posedMesh' % deformer)

        updateInversion(deformer)

#        cmds.connectAttr('%s.input[0].inputGeometry' % foc_blend_shape, '%s.bindPoseMesh' % deformer)
        cmds.setAttr('%s.activate' % deformer, True)
        return invertedShape

    finally:
        cmds.undoInfo(closeChunk=True)

def getShape(node):
    """@brief Returns a shape node from a given transform or shape.

    @param[in] node Name of the node.
    @return The associated shape node.
    """
    if cmds.nodeType(node) == 'transform':
        shapes = cmds.listRelatives(node, shapes=True, path=True)
        if not shapes:
            raise RuntimeError, '%s has no shape' % node
        return shapes[0]
    elif cmds.nodeType(node) in ['mesh', 'nurbsCurve', 'nurbsSurface']:
        return node


def getMObject(node):
    """@brief Gets the dag path of a node.

    @param[in] node Name of the node.
    @return The dag path of a node.
    """
    selectionList = OpenMaya.MSelectionList()
    selectionList.add(node)
    oNode = OpenMaya.MObject()
    selectionList.getDependNode(0, oNode)
    return oNode


def getDagPath(node):
    """@brief Gets the dag path of a node.

    @param[in] node Name of the node.
    @return The dag path of a node.
    """
    selectionList = OpenMaya.MSelectionList()
    selectionList.add(node)
    pathNode = OpenMaya.MDagPath()
    selectionList.getDagPath(0, pathNode)
    return pathNode


def getMeshPoints(path, space=OpenMaya.MSpace.kObject):
    """@brief Get the control point positions of a geometry node.

    @param[in] path Name or dag path of a node.
    @param[in] space Space to get the points.
    @return The MPointArray of points.
    """
    if isinstance(path, str) or isinstance(path, unicode):
        path = getDagPath(getShape(path))
    itGeo = OpenMaya.MItGeometry(path)
    points = OpenMaya.MPointArray()
    itGeo.allPositions(points, space)
    return points

#def getPoints(plug, space=OpenMaya.MSpace.kObject):
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


def setPoints(path, points, space=OpenMaya.MSpace.kObject):
    """@brief Set the control points positions of a geometry node.

    @param[in] path Name or dag path of a node.
    @param[in] points MPointArray of points.
    @param[in] space Space to get the points.
    """
    if isinstance(path, str) or isinstance(path, unicode):
        path = getDagPath(getShape(path))
    itGeo = OpenMaya.MItGeometry(path)
    itGeo.setAllPositions(points, space)


def setMatrixRow(matrix, newVector, row):
    """@brief Sets a matrix row with an MVector or MPoint.

    @param[in/out] matrix Matrix to set.
    @param[in] newVector Vector to use.
    @param[in] row Row number.
    """
    setMatrixCell(matrix, newVector.x, row, 0)
    setMatrixCell(matrix, newVector.y, row, 1)
    setMatrixCell(matrix, newVector.z, row, 2)


def setMatrixCell(matrix, value, row, column):
    """@brief Sets a matrix cell

    @param[in/out] matrix Matrix to set.
    @param[in] value Value to set cell.
    @param[in] row Row number.
    @param[in] column Column number.
    """
    OpenMaya.MScriptUtil.setDoubleArray(matrix[row], column, value)

