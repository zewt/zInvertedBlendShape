import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import pymel.core
import math

API_VERSION = OpenMaya.MGlobal.apiVersion()

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
    aActivate = OpenMaya.MObject()
    attrInvertedTweak = OpenMaya.MObject()

#    def setInternalValueInContext(self, plug, handle, ctx):
#        try:
#            print 'set', plug.info(), handle
#            array = OpenMaya.MUintArray()
#            handle.acceptedTypeIds(array)
#            print array
#        except Exception as e:
#            print 'error', e
##        print handle, ctx
#        return False


    def get_matrixes(self, data):
        if API_VERSION < 201600:
            inputAttribute = OpenMayaMPx.cvar.MPxDeformerNode_input
            inputGeom = OpenMayaMPx.cvar.MPxDeformerNode_inputGeom
        else:
            inputAttribute = OpenMayaMPx.cvar.MPxGeometryFilter_input
            inputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_inputGeom

        hMatrix = data.inputArrayValue(testDeformer.aMatrix)
        matrixElementCount = hMatrix.elementCount()
        matrixes = []
        for i in xrange(matrixElementCount):
            self.jumpToElement(hMatrix, i)
            matrixes.append(hMatrix.inputValue().asMatrix())
        return matrixes

    def update_inverted(self, data):
        matrixes = self.get_matrixes(data)

#        bindPoseMeshHandle = data.inputValue(testDeformer.aBindPoseMesh)
#        posedMeshHandle = data.inputValue(testDeformer.aPosedMesh)
#        bindPoseGeo = OpenMaya.MItGeometry(bindPoseMeshHandle)
#        posedMeshGeo = OpenMaya.MItGeometry(posedMeshHandle)
#        bindPoseGeoPositions = OpenMaya.MPointArray()
#        bindPoseGeo.allPositions(bindPoseGeoPositions)
#        posedMeshGeoPositions = OpenMaya.MPointArray()
#        posedMeshGeo.allPositions(posedMeshGeoPositions)

        outputInvertedTweak = data.outputArrayValue(self.attrInvertedTweak)
        builder = outputInvertedTweak.builder()

        tweakData = data.inputArrayValue(self.attrTweak)
        for item in iterate_array_handle(tweakData):
            thisValue = tweakData.inputValue()

            idx = arrayCurrentIndex(tweakData)
            newElement = builder.addElement(idx)

            # log('%s' % tweakData)
            index = tweakData.elementIndex()

            # Get the associated positions in the base and posed meshes.
#            bindPosePosition = bindPoseGeoPositions[index]
#            posedPosition = posedMeshGeoPositions[index]

            delta = thisValue.asFloat3()
            delta = OpenMaya.MVector(*delta)

            offset = delta
            if idx < len(matrixes):
                offset *= matrixes[idx]
            newElement.set3Float(*offset)

        outputInvertedTweak.set(builder)
        outputInvertedTweak.setAllClean()
        data.setClean(self.attrInvertedTweak)

    def compute(self, plug, data):
#        print 'Compute: %s, %i, %i' % (plug.info(), plug.isElement(), plug.isChild())
        # We have to handle updating invertedTweak for both elements of the array and the
        # array itself, or things won't update reliably.
        if plug.isChild() and plug.parent() == self.attrInvertedTweak:
            # log('Compute inverted')
            self.update_inverted(data)
            # log('Done compute inverted')
            return

        if plug == self.attrInvertedTweak:
            # log('Compute inverted outer')
            self.update_inverted(data)
            # log('Done compute inverted outer')
            return

        if plug == OpenMayaMPx.cvar.MPxGeometryFilter_outputGeom:
            # log('Compute geom')

            # We should be able to just call the base implementation of compute(), but that's broken.
            index = plug.logicalIndex()
            hInput = data.inputArrayValue(OpenMayaMPx.cvar.MPxGeometryFilter_input)
            hInput.jumpToArrayElement(index)

            hInputElement = hInput.inputValue()	
            hInputGeom = hInputElement.child(OpenMayaMPx.cvar.MPxGeometryFilter_inputGeom)
            hGroup = hInputElement.child(OpenMayaMPx.cvar.MPxGeometryFilter_groupId)

            hOutput = data.outputValue(plug)
            hOutput.copy(hInputGeom)
            itGeo = OpenMaya.MItGeometry(hOutput, hGroup.asLong(), False)

            # We have to read the invertedTweak array through a plug.  If we use the MDataBlock like
            # we're supposed to, it won't update.  The basicBlendShape.cpp sample does this, saying
            # "inputPointsTarget is computed on pull, so can't just read it out of the datablock",
            # but it doesn't explain what the hell that means and why we can't do the normal thing.
            invertedTweakPlug = OpenMaya.MPlug(self.thisMObject(), testDeformer.attrInvertedTweak)
            invertedTweakPlug = invertedTweakPlug.elementByLogicalIndex(0)
            obj = invertedTweakPlug.asMObject(data.context())

            invertedTweakData = data.inputArrayValue(testDeformer.attrInvertedTweak)





            # This is a simple relative tweak.  In fact, we should be able to just connect our
            # .invertedTweak plug to the vlist input of a tweak node, but Maya is bad at connecting
            # arrays.
            for vertex in iterate_array(itGeo):
                index = vertex.index()
                pt = vertex.position()

                # Advance the vertex data until we get to the same index.
                if not advance_array_to_index(invertedTweakData, index):
                    continue

                delta = invertedTweakData.inputValue().asFloat3()
                delta = OpenMaya.MVector(*delta)
                vertex.setPosition(vertex.position() + delta)

            data.setClean(plug)
            # log('Done compute geom')
            
            return

        return super(testDeformer, self).compute(plug, data)

#    def setDependentsDirty(self, plug, affectedPlugs):
#        log('dirty: %s' % plug.info())

#        if plug == self.attrTweak:
#            wtf = OpenMaya.MPlug(self.thisMObject(), self.attrInvertedTweak)
#            if wtf.numElements() > 0:
#                wtf = wtf.elementByLogicalIndex(0)
#                log('--> %s' % wtf.info())
#                affectedPlugs.append(wtf)
                
#        return super(testDeformer, self).setDependentsDirty(plug, affectedPlugs)

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

    if API_VERSION < 201600:
        outputGeom = OpenMayaMPx.cvar.MPxDeformerNode_outputGeom
    else:
        outputGeom = OpenMayaMPx.cvar.MPxGeometryFilter_outputGeom

    testDeformer.aActivate = nAttr.create('activate', 'activate', OpenMaya.MFnNumericData.kBoolean)
    testDeformer.addAttribute(testDeformer.aActivate)
    testDeformer.attributeAffects(testDeformer.aActivate, outputGeom)

    testDeformer.attrInvertedTweak = nAttr.createPoint('invertedTweak', 'itwk')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    testDeformer.addAttribute(testDeformer.attrInvertedTweak)
    testDeformer.attributeAffects(testDeformer.attrInvertedTweak, outputGeom)

    # The tweak input.  This is connected to the output blend shape to receive edits.
    # Edits are inverted and saved to invertedTweak.
    testDeformer.attrTweak = nAttr.createPoint('tweak', 'twk')
    nAttr.setArray(True)
    nAttr.setUsesArrayDataBuilder(True)
    nAttr.setStorable(False)
    testDeformer.addAttribute(testDeformer.attrTweak)
    testDeformer.attributeAffects(testDeformer.attrTweak, testDeformer.attrInvertedTweak)
    testDeformer.attributeAffects(testDeformer.attrTweak, outputGeom)

#    testDeformer.aBindPoseMesh = tAttr.create('bindPoseMesh', 'bpm', OpenMaya.MFnData.kMesh)
#    testDeformer.addAttribute(testDeformer.aBindPoseMesh)

    # We don't use this directly.  It's used by updateInversion to remember where the base
    # mesh was when the deformer was initially created.
    testDeformer.aPosedMesh = tAttr.create('posedMesh', 'pm', OpenMaya.MFnData.kMesh)
    testDeformer.addAttribute(testDeformer.aPosedMesh)

    testDeformer.aMatrix = mAttr.create('inversionMatrix', 'im')
    mAttr.setArray(True)
    mAttr.setUsesArrayDataBuilder(True)
    testDeformer.addAttribute(testDeformer.aMatrix)

def initializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.registerNode(testDeformer.kPluginNodeName, testDeformer.kPluginNodeId, creator,
            initialize, OpenMayaMPx.MPxNode.kDeformerNode)

def uninitializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.deregisterNode(testDeformer.kPluginNodeId)

