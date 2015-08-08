import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import pymel.core
import math, traceback, time

last_time = time.time()
def log_time(s):
    global last_time
    delta = time.time() - last_time
    last_time = time.time()
    print '%f: %s' % (delta, s)

if OpenMaya.MGlobal.apiVersion() < 201600:
    MPxGeometryFilter_outputGeom = OpenMayaMPx.cvar.MPxDeformerNode_outputGeom
    MPxGeometryFilter_input = OpenMayaMPx.cvar.MPxDeformerNode_input
    MPxGeometryFilter_inputGeom = OpenMayaMPx.cvar.MPxDeformerNode_inputGeom
    MPxGeometryFilter_groupId = OpenMayaMPx.cvar.MPxDeformerNode_groupId
else:
    MPxGeometryFilter_outputGeom = outputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_outputGeom
    MPxGeometryFilter_input = OpenMayaMPx.cvar.MPxGeometryFilter_input
    MPxGeometryFilter_inputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_inputGeom
    MPxGeometryFilter_groupId = OpenMayaMPx.cvar.MPxGeometryFilter_groupId

def array_current_index(array):
    """
    Return the current index (elementIndex()) of a MArrayDataHandle, or -1 if the
    current index isn't valid, probably because the array is empty.
    """
    try:
        return array.elementIndex()
    except RuntimeError as e:
        # If the array is empty, elementIndex raises an error.
        return -1

def advance_array_to_index(array, idx):
    """
    Advance array forwards until its index is >= idx.  Return true
    if the value was found, or false if we've advanced beyond it because
    the index doesn't exist.

    This is intended to be used when advancing two arrays in parallel.
    """
    while array_current_index(array) < idx:
        try:
            array.next()
        except RuntimeError as e:
            # We've advanced beyond the end of the array.
            return False

    return array_current_index(array) == idx

def advance_geometry_iterator_to_index(array, idx):
    """
    The same as advance_array_to_index, but for geometry iterators.
    Advance array forwards until its index is >= idx.  Return true
    if the value was found, or false if we've advanced beyond it because
    the index doesn't exist.

    This is intended to be used when advancing two arrays in parallel.
    """
    while array_current_index(array) < idx:
        try:
            array.next()
        except RuntimeError as e:
            # We've advanced beyond the end of the array.
            return False

    return array_current_index(array) == idx

def iterate_array(array):
    """
    Mostly fix geometry iterator iteration.
    """
    while not array.isDone():
        yield array
        array.next()

def iterate_array_handle(array):
    """
    Mostly fix MArrayDataHandle array iteration.
    """
    while True:
        # Call elementIndex() to see if there are any values at all.  It'll throw RuntimeError
        # if there aren't.
        try:
            array.elementIndex()
        except RuntimeError as e:
            # We've advanced beyond the end of the array.
            break

        yield array

        try:
            array.next()
        except RuntimeError as e:
            break

class sculptableInvertedBlendShape(OpenMayaMPx.MPxDeformerNode):
    # I haven't requested an ID block yet.  For now use a number in the devkit sample
    # range, so it won't conflict with anything important or anyone's internal use IDs.
    pluginNodeId = OpenMaya.MTypeId(0xEA520)

    def __init__(self):
        super(sculptableInvertedBlendShape, self).__init__()
        self.cached_inversion_matrices = None

    def get_matrices(self, data_block):
        """
        Return a list of the current value of .inversionMatrices.

        This caches the value of the list.
        """
        # This is accessed a lot, and unlike the tweaks it always contains a value for every vertex,
        # so retrieving this is relatively expensive.  Cache the results.
        if self.cached_inversion_matrices is not None:
            return self.cached_inversion_matrices

        matrix_array = data_block.inputArrayValue(sculptableInvertedBlendShape.matrix_attr)

        matrices = []
        for item in iterate_array_handle(matrix_array):
            idx = matrix_array.elementIndex()

            # If this is a sparse array, fill it in.  This array is usually not sparse.
            if idx > len(matrices):
                matrices.append([OpenMaya.MMatrix()] * (idx - len(matrices)))
            matrices.append(matrix_array.inputValue().asMatrix())

        self.cached_inversion_matrices = matrices
        return matrices

    def get_one_tweak_from_inverted(self, data_block, start_index):
        """
        Given the current invertedTweak, return the current tweak data.
        """
        matrices = self.get_matrices(data_block)

        inverted_tweak_data = data_block.inputArrayValue(self.inverted_tweak_attr)

        # If we're starting at a specified index, jump to it.
        try:
            inverted_tweak_data.jumpToElement(start_index)
        except RuntimeError as e:
            # kInvalidParameter: No element at given index
            # If there's nothing at this index, then the tweak is zero.
            return OpenMaya.MVector(0,0,0)

        thisValue = inverted_tweak_data.inputValue()

        idx = inverted_tweak_data.elementIndex()

        delta = thisValue.asFloat3()
        delta = OpenMaya.MVector(*delta)

        offset = delta
        if idx < len(matrices):
            offset *= matrices[idx]

        return offset

    def get_tweak_array_from_inverted(self, data_block, builder):
        """
        Set .invertedTweak from the current value of .tweak and input matrices.
        Given the current invertedTweak, return the current tweak data.
        """
        matrices = self.get_matrices(data_block)

        inverted_tweak_data = data_block.inputArrayValue(self.inverted_tweak_attr)

        for item in iterate_array_handle(inverted_tweak_data):
            thisValue = inverted_tweak_data.inputValue()

            idx = inverted_tweak_data.elementIndex()

            delta = thisValue.asFloat3()
            delta = OpenMaya.MVector(*delta)

            if idx < len(matrices):
                mat = matrices[idx]
                mat = mat.inverse()
                delta *= mat

            element = builder.addElement(idx)
            element.set3Float(delta.x, delta.y, delta.z)

    def set_tweak_from_inverted(self, data_block):
        """
        Set .tweak from the current value of .invertedTweak and input matrices.
        """
        output_tweak = data_block.outputArrayValue(self.tweak_attr)
        builder = output_tweak.builder()

        values = self.get_tweak_array_from_inverted(data_block, builder)
        output_tweak.set(builder)
        output_tweak.setAllClean()

    def set_inverted_from_tweak(self, data_block):
        """
        Update .inverted_tweak_attr from the current value of .tweak.
        """
        tweak_data = data_block.inputArrayValue(self.tweak_attr)

        matrices = self.get_matrices(data_block)

        outputInvertedTweak = data_block.outputArrayValue(self.inverted_tweak_attr)

        # Don't use outputInvertedTweak.builder().  That'll return a builder containing
        # the existing data of the plug.  If there are tweak indexes that are now (0,0,0)
        # which used to have data, we'd need to remove them in the short-circuit case
        # below, and there's no fast way to do that.  Create a new builder instead.
        # builder = outputInvertedTweak.builder()
        builder = OpenMaya.MArrayDataBuilder(data_block, self.inverted_tweak_attr, 0)

        # Always add an element at index 0, or compute() will be called every frame.
        # This seems like a quirk of the tweak connection.
        newElement = builder.addElement(0)
        newElement.set3Float(0,0,0)

        for item in iterate_array_handle(tweak_data):
            thisValue = tweak_data.inputValue()
            delta = thisValue.asFloat3()

            # Skip zero tweaks.  Most blend shapes will have small, localized changes to
            # some part of the mesh, so we save a lot of time by not processing vertices
            # that haven't been changed.  This also saves time during MPxGeometryFilter_outputGeom
            # calculation, since that also won't spend any time deforming unchanged vertices.
            if abs(delta[0]) < 0.001 and abs(delta[1]) < 0.001 and abs(delta[2]) < 0.001:
                continue

            delta = OpenMaya.MVector(*delta)

            idx = array_current_index(tweak_data)
            if idx < len(matrices):
                delta *= matrices[idx]

            newElement = builder.addElement(idx)
            newElement.set3Float(*delta)

        outputInvertedTweak.set(builder)
        outputInvertedTweak.setAllClean()
        data_block.setClean(self.inverted_tweak_attr)
      
    def compute(self, plug, data):
        # We have to handle updating invertedTweak for both elements of the array and the
        # array itself, or things won't update reliably.
        # print 'Compute: %s, %i, %i' % (plug.info(), plug.isElement(), plug.isChild())
        if plug == self.inverted_tweak_attr or (plug.isChild() and plug.parent() == self.inverted_tweak_attr):
            self.set_inverted_from_tweak(data)
            return

        if plug == MPxGeometryFilter_outputGeom:
            # We should be able to just call the base implementation of compute(), but that's broken.
            index = plug.logicalIndex()
            input_array = data.inputArrayValue(MPxGeometryFilter_input)
            input_array.jumpToArrayElement(index)

            input_element_handle = input_array.inputValue()	
            input_geom = input_element_handle.child(MPxGeometryFilter_inputGeom)
            group_id_handle = input_element_handle.child(MPxGeometryFilter_groupId)

            output_handle = data.outputValue(plug)
            output_handle.copy(input_geom)
            geometry_iterator = OpenMaya.MItGeometry(output_handle, group_id_handle.asLong(), False)

            # We have to read the invertedTweak array through a plug.  If we use the MDataBlock like
            # we're supposed to, it won't update.  The basicBlendShape.cpp sample does this, saying
            # "inputPointsTarget is computed on pull, so can't just read it out of the datablock",
            # but it doesn't explain what the hell that means and why we can't do the normal thing.
            inverted_tweak_plug = OpenMaya.MPlug(self.thisMObject(), sculptableInvertedBlendShape.inverted_tweak_attr)
            inverted_tweak_plug = inverted_tweak_plug.elementByLogicalIndex(0)
            inverted_tweak_plug.asMObject(data.context())

            inverted_tweak_data = data.inputArrayValue(sculptableInvertedBlendShape.inverted_tweak_attr)

            # This is a simple relative tweak.  In fact, we should be able to just connect our
            # .invertedTweak plug to the vlist input of a tweak node, but Maya is bad at connecting
            # arrays.
            points = OpenMaya.MPointArray()
            geometry_iterator.allPositions(points)

            # We have the input geometry iterator, and the list of tweaks.  The tweak list is
            # usually sparse, so loop through that rather than the geometry.
            for tweak in iterate_array_handle(inverted_tweak_data):
                index = tweak.elementIndex()
                if index >= points.length():
                    break

                point = points[index]
                delta = inverted_tweak_data.inputValue().asFloat3()
                points.set(index, point[0] + delta[0], point[1] + delta[1], point[2] + delta[2])

            geometry_iterator.setAllPositions(points)

            data.setClean(plug)
            return

        return super(sculptableInvertedBlendShape, self).compute(plug, data)

    def setInternalValueInContext(self, plug, handle, context):
        try:
            if plug == self.recalculate_tweak_attr:
                # This attribute is only used to trigger this recalculation.
                self.set_tweak_from_inverted(self._forceCache())
            elif plug == sculptableInvertedBlendShape.matrix_attr:
                # .inversionMatrices is changing, so throw away our cache.
                self.cached_inversion_matrices = None
        except Exception as e:
            print 'setInternalValueInContext error: %s' % e
            traceback.print_exc()

        return super(sculptableInvertedBlendShape, self).setInternalValueInContext(plug, handle, context)

    def jumpToElement(self, hArray, index):
        """@brief Jumps an array handle to a logical index and uses the builder if necessary.

        @param[in/out] hArray MArrayDataHandle to jump.
        @param[in] index Logical index.
        """
        try:
            hArray.jumpToElement(index)
        except:
            builder = hArray.builder()
            builder.addElement(index)
            hArray.set(builder)
            hArray.jumpToElement(index)


def creator():
    return OpenMayaMPx.asMPxPtr(sculptableInvertedBlendShape())

def initialize():
    mAttr = OpenMaya.MFnMatrixAttribute()
    tAttr = OpenMaya.MFnTypedAttribute()
    nAttr = OpenMaya.MFnNumericAttribute()
    cmpAttr = OpenMaya.MFnCompoundAttribute()

    # The main, stored data of the deformer, as a list of tweaks (vertex deltas) for the input
    # geometry.
    sculptableInvertedBlendShape.inverted_tweak_attr = nAttr.createPoint('invertedTweak', 'itwk')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    sculptableInvertedBlendShape.addAttribute(sculptableInvertedBlendShape.inverted_tweak_attr)
    sculptableInvertedBlendShape.attributeAffects(sculptableInvertedBlendShape.inverted_tweak_attr, MPxGeometryFilter_outputGeom)

    # The tweak input.  This is connected to the output blend shape to receive edits.
    # Edits are inverted and saved to invertedTweak, and this can be read to retrieve
    # the tweaks relative to the current inversion matrices.
    sculptableInvertedBlendShape.tweak_attr = nAttr.createPoint('tweak', 'twk')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    nAttr.setStorable(False)
    sculptableInvertedBlendShape.addAttribute(sculptableInvertedBlendShape.tweak_attr)
    sculptableInvertedBlendShape.attributeAffects(sculptableInvertedBlendShape.tweak_attr, sculptableInvertedBlendShape.inverted_tweak_attr)
    sculptableInvertedBlendShape.attributeAffects(sculptableInvertedBlendShape.tweak_attr, MPxGeometryFilter_outputGeom)

    # A matrix per input vertex, giving the transform from the base shape to the current
    # pose of the mesh being sculpted.  Note that changing this will not automatically
    # update tweak_attr, since this doesn't seem to update attached tweakLocation meshes
    # correctly.  To force this update to happen, a value is written to .recalculateTweak.
    sculptableInvertedBlendShape.matrix_attr = mAttr.create('inversionMatrix', 'im')
    mAttr.setArray(True)
    mAttr.setInternal(True)
    mAttr.setUsesArrayDataBuilder(True)
    sculptableInvertedBlendShape.addAttribute(sculptableInvertedBlendShape.matrix_attr)
    # sculptableInvertedBlendShape.attributeAffects(sculptableInvertedBlendShape.matrix_attr, sculptableInvertedBlendShape.tweak_attr)

    # This is a hack: write to this attribute to force .tweak to be recalculated from
    # .invertedTweak.  We should use a command for this, but I can't find any way to
    # get our MPxDeformerNode instance from a command like you can natively.
    sculptableInvertedBlendShape.recalculate_tweak_attr = nAttr.create('recalculateTweak', 'rct', OpenMaya.MFnNumericData.kBoolean)
    nAttr.setStorable(False)
    nAttr.setKeyable(False)
    nAttr.setInternal(True)
    sculptableInvertedBlendShape.addAttribute(sculptableInvertedBlendShape.recalculate_tweak_attr)

    # This attribute is only used to temporarily store the original tweak node while
    # we're redirecting tweaks for a mesh to us.
    #
    # We don't really need to enable usesArrayDataBuilder since this isn't meant to
    # actually receive data, but if it does and that's not enabled it can crash.
    sculptableInvertedBlendShape.saved_tweak_connection_attr = nAttr.createPoint('savedTweakConnection', 'stc')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    nAttr.setStorable(False)
    sculptableInvertedBlendShape.addAttribute(sculptableInvertedBlendShape.saved_tweak_connection_attr)

def initializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.registerNode('sculptableInvertedBlendShape', sculptableInvertedBlendShape.pluginNodeId, creator,
            initialize, OpenMayaMPx.MPxNode.kDeformerNode)

def uninitializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.deregisterNode(sculptableInvertedBlendShape.pluginNodeId)

