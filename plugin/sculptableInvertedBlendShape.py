import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import pymel.core
import math, traceback, time

API_VERSION = OpenMaya.MGlobal.apiVersion()

last_time = time.time()
def log_time(s):
    global last_time
    delta = time.time() - last_time
    last_time = time.time()
    print '%f: %s' % (delta, s)

if API_VERSION < 201600:
    MPxGeometryFilter_outputGeom = OpenMayaMPx.cvar.MPxDeformerNode_outputGeom
    MPxGeometryFilter_input = OpenMayaMPx.cvar.MPxDeformerNode_input
    MPxGeometryFilter_inputGeom = OpenMayaMPx.cvar.MPxDeformerNode_inputGeom
    MPxGeometryFilter_groupId = OpenMayaMPx.cvar.MPxDeformerNode_groupId
else:
    MPxGeometryFilter_outputGeom = outputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_outputGeom
    MPxGeometryFilter_input = OpenMayaMPx.cvar.MPxGeometryFilter_input
    MPxGeometryFilter_inputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_inputGeom
    MPxGeometryFilter_groupId = OpenMayaMPx.cvar.MPxGeometryFilter_groupId

def arrayCurrentIndex(array):
    try:
        return array.elementIndex()
    except RuntimeError as e:
        # If the array is empty, elementIndex raises an error.
        # element
        return -1

def advance_array_to_index(array, idx):
    """
    Advance array forwards until its index is >= idx.  Return true
    if the value was found, or false if we've advanced beyond it because
    the index doesn't exist.

    This is intended to be used when advancing two arrays in parallel.
    """
    while arrayCurrentIndex(array) < idx:
        try:
            array.next()
        except RuntimeError as e:
            # We've advanced beyond the end of the array.
            return False

    return arrayCurrentIndex(array) == idx

def advance_geometry_iterator_to_index(array, idx):
    """
    The same as advance_array_to_index, but for geometry iterators.
    Advance array forwards until its index is >= idx.  Return true
    if the value was found, or false if we've advanced beyond it because
    the index doesn't exist.

    This is intended to be used when advancing two arrays in parallel.
    """
    while arrayCurrentIndex(array) < idx:
        try:
            array.next()
        except RuntimeError as e:
            # We've advanced beyond the end of the array.
            return False

    return arrayCurrentIndex(array) == idx

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

_idx = 0
def log(s):
    global _idx
    _idx += 1
    print '%i: %s' % (_idx, s)

class testDeformer(OpenMayaMPx.MPxDeformerNode):
    kPluginNodeName = "testDeformer"
    kPluginNodeId = OpenMaya.MTypeId(0x00115809)
    aMatrix = OpenMaya.MObject()
    attrInvertedTweak = OpenMaya.MObject()

    def __init__(self):
        super(testDeformer, self).__init__()
        self.inversionMatricesDirty = True

    def get_matrices(self, data):
        # This is accessed a lot, and unlike the tweaks it always contains a value for every vertex,
        # so retrieving this is relatively expensive.  Cache the results.
        if not self.inversionMatricesDirty:
            return self.cachedInversionMatrices

        hMatrix = data.inputArrayValue(testDeformer.aMatrix)

        matrices = []
        for item in iterate_array_handle(hMatrix):
            idx = hMatrix.elementIndex()

            # If this is a sparse array, fill it in.  This array is usually not sparse.
            if idx > len(matrices):
                matrices.append([OpenMaya.MMatrix()] * (idx - len(matrices)))
            matrices.append(hMatrix.inputValue().asMatrix())

        self.cachedInversionMatrices = matrices
        self.inversionMatricesDirty = False 
        return matrices

    def get_one_tweak_from_inverted(self, data, start_index):
        """
        Given the current invertedTweak, return the current tweak data.
        """
        matrices = self.get_matrices(data)

        invertedTweakData = data.inputArrayValue(self.attrInvertedTweak)

        # If we're starting at a specified index, jump to it.
        try:
            invertedTweakData.jumpToElement(start_index)
        except RuntimeError as e:
            # kInvalidParameter: No element at given index
            # If there's nothing at this index, then the tweak is zero.
            return OpenMaya.MVector(0,0,0)

        thisValue = invertedTweakData.inputValue()

        idx = invertedTweakData.elementIndex()

        delta = thisValue.asFloat3()
        delta = OpenMaya.MVector(*delta)

        offset = delta
        if idx < len(matrices):
            offset *= matrices[idx]

        return offset

    def get_tweak_array_from_inverted(self, data, builder):
        """
        Given the current invertedTweak, return the current tweak data.
        """
        matrices = self.get_matrices(data)

        invertedTweakData = data.inputArrayValue(self.attrInvertedTweak)

        for item in iterate_array_handle(invertedTweakData):
            thisValue = invertedTweakData.inputValue()

            idx = invertedTweakData.elementIndex()

            delta = thisValue.asFloat3()
            delta = OpenMaya.MVector(*delta)

            if idx < len(matrices):
                mat = matrices[idx]
                mat = mat.inverse()
                delta *= mat

            element = builder.addElement(idx)
            element.set3Float(delta.x, delta.y, delta.z)

    def set_inverted_from_tweak(self, dataBlock, tweakData):
        matrices = self.get_matrices(dataBlock)

        outputInvertedTweak = dataBlock.outputArrayValue(self.attrInvertedTweak)
        builder = outputInvertedTweak.builder()

        for item in iterate_array_handle(tweakData):
            thisValue = tweakData.inputValue()
            delta = thisValue.asFloat3()

            # Skip zero tweaks.  Most blend shapes will have small, localized changes to
            # some part of the mesh, so we save a lot of time by not processing vertices
            # that haven't been changed.
            if abs(delta[0]) < 0.001 and abs(delta[1]) < 0.001 and abs(delta[2]) < 0.001:
                continue

            delta = OpenMaya.MVector(*delta)

            idx = arrayCurrentIndex(tweakData)
            if idx < len(matrices):
                delta *= matrices[idx]

            newElement = builder.addElement(idx)
            newElement.set3Float(*delta)

        outputInvertedTweak.set(builder)
        outputInvertedTweak.setAllClean()
        dataBlock.setClean(self.attrInvertedTweak)

       
    def deriveCurrentTweak(self):
        """
        Set .tweak from the current values of .invertedTweak and input matrices.

        This is used when updating tweak for a new pose.
        """
        dataBlock = self._forceCache()

        outputTweak = dataBlock.outputArrayValue(self.attrTweak)
        builder = outputTweak.builder()

        values = self.get_tweak_array_from_inverted(dataBlock, builder)
        outputTweak.set(builder)
        outputTweak.setAllClean()

    def compute(self, plug, data):
        # We have to handle updating invertedTweak for both elements of the array and the
        # array itself, or things won't update reliably.
        # print 'Compute: %s, %i, %i' % (plug.info(), plug.isElement(), plug.isChild())
        if plug.isChild() and plug.parent() == self.attrInvertedTweak:
            # log('Compute inverted')
            tweakData = data.inputArrayValue(self.attrTweak)
            self.set_inverted_from_tweak(data, tweakData)
            # log('Done compute inverted')
            return

        if plug == self.attrInvertedTweak:
            # log('Compute inverted outer')
            tweakData = data.inputArrayValue(self.attrTweak)
            self.set_inverted_from_tweak(data, tweakData)
            # log('Done compute inverted outer')
            return

        if plug == MPxGeometryFilter_outputGeom:
            # log('Compute geom')

            # We should be able to just call the base implementation of compute(), but that's broken.
            index = plug.logicalIndex()
            hInput = data.inputArrayValue(MPxGeometryFilter_input)
            hInput.jumpToArrayElement(index)

            hInputElement = hInput.inputValue()	
            hInputGeom = hInputElement.child(MPxGeometryFilter_inputGeom)
            hGroup = hInputElement.child(MPxGeometryFilter_groupId)

            hOutput = data.outputValue(plug)
            hOutput.copy(hInputGeom)
            itGeo = OpenMaya.MItGeometry(hOutput, hGroup.asLong(), False)

            # We have to read the invertedTweak array through a plug.  If we use the MDataBlock like
            # we're supposed to, it won't update.  The basicBlendShape.cpp sample does this, saying
            # "inputPointsTarget is computed on pull, so can't just read it out of the datablock",
            # but it doesn't explain what the hell that means and why we can't do the normal thing.
            invertedTweakPlug = OpenMaya.MPlug(self.thisMObject(), testDeformer.attrInvertedTweak)
            invertedTweakPlug = invertedTweakPlug.elementByLogicalIndex(0)
            invertedTweakPlug.asMObject(data.context())

            invertedTweakData = data.inputArrayValue(testDeformer.attrInvertedTweak)

            # This is a simple relative tweak.  In fact, we should be able to just connect our
            # .invertedTweak plug to the vlist input of a tweak node, but Maya is bad at connecting
            # arrays.
            points = OpenMaya.MPointArray()
            itGeo.allPositions(points)

            # We have the input geometry iterator, and the list of tweaks.  The tweak list is
            # usually sparse, so loop through that rather than the geometry.
            for tweak in iterate_array_handle(invertedTweakData):
                index = tweak.elementIndex()
                if index >= points.length():
                    break

                point = points[index]
                delta = invertedTweakData.inputValue().asFloat3()
                points.set(index, point[0] + delta[0], point[1] + delta[1], point[2] + delta[2])

            itGeo.setAllPositions(points)

            data.setClean(plug)
            # log('Done compute geom')
            
            return

        return super(testDeformer, self).compute(plug, data)

    def setInternalValueInContext(self, plug, handle, context):
        try:
            if plug == self.attrRecalculateTweak:
                # This attribute is only used to trigger this recalculation.
                self.deriveCurrentTweak()
            elif plug == testDeformer.aMatrix:
                # .inversionMatrices is changing, so throw away our cache.
                self.inversionMatricesDirty = True
        except Exception as e:
            print 'setInternalValueInContext error: %s' % e
            traceback.print_exc()

        return super(testDeformer, self).setInternalValueInContext(plug, handle, context)

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
    return OpenMayaMPx.asMPxPtr(testDeformer())

def initialize():
    mAttr = OpenMaya.MFnMatrixAttribute()
    tAttr = OpenMaya.MFnTypedAttribute()
    nAttr = OpenMaya.MFnNumericAttribute()
    cmpAttr = OpenMaya.MFnCompoundAttribute()

    testDeformer.attrInvertedTweak = nAttr.createPoint('invertedTweak', 'itwk')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    testDeformer.addAttribute(testDeformer.attrInvertedTweak)
    testDeformer.attributeAffects(testDeformer.attrInvertedTweak, MPxGeometryFilter_outputGeom)

    # The tweak input.  This is connected to the output blend shape to receive edits.
    # Edits are inverted and saved to invertedTweak.
    testDeformer.attrTweak = nAttr.createPoint('tweak', 'twk')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    nAttr.setStorable(False)
    testDeformer.addAttribute(testDeformer.attrTweak)
    # We don't actually need to declare that tweak affects invertedTweak, since this is
    # only ever set as a property, and never derived by compute().
    testDeformer.attributeAffects(testDeformer.attrTweak, testDeformer.attrInvertedTweak)
    testDeformer.attributeAffects(testDeformer.attrTweak, MPxGeometryFilter_outputGeom)

    # We don't use this directly.  It's used by updateInversion to remember where the base
    # mesh was when the deformer was initially created.
    testDeformer.aPosedMesh = tAttr.create('posedMesh', 'pm', OpenMaya.MFnData.kMesh)
    testDeformer.addAttribute(testDeformer.aPosedMesh)

    testDeformer.aMatrix = mAttr.create('inversionMatrix', 'im')
    mAttr.setArray(True)
    mAttr.setInternal(True)
    mAttr.setUsesArrayDataBuilder(True)
    testDeformer.addAttribute(testDeformer.aMatrix)
    testDeformer.attributeAffects(testDeformer.aMatrix, testDeformer.attrTweak)
#    testDeformer.attributeAffects(testDeformer.aMatrix, MPxGeometryFilter_outputGeom)

    # This is a hack: write to this attribute to force .tweak to be recalculated from
    # .invertedTweak.  We should use a command for this, but I can't find any way to
    # get our MPxDeformerNode instance from a command like you can natively.
    testDeformer.attrRecalculateTweak = nAttr.create('recalculateTweak', 'rct', OpenMaya.MFnNumericData.kBoolean)
    nAttr.setStorable(False)
    nAttr.setInternal(True)
    testDeformer.addAttribute(testDeformer.attrRecalculateTweak)

    # This attribute is only used to temporarily store the original tweak node while
    # we're redirecting tweaks for a mesh to us.
    #
    # We don't really need to enable usesArrayDataBuilder since this isn't meant to
    # actually receive data, but if it does and that's not enabled it can crash.
    testDeformer.attrSavedTweakConnection = nAttr.createPoint('savedTweakConnection', 'stc')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    nAttr.setStorable(False)
    testDeformer.addAttribute(testDeformer.attrSavedTweakConnection)

def initializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    
    plugin.registerNode(testDeformer.kPluginNodeName, testDeformer.kPluginNodeId, creator,
            initialize, OpenMayaMPx.MPxNode.kDeformerNode)

def uninitializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.deregisterNode(testDeformer.kPluginNodeId)

