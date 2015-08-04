import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import pymel.core
import math, traceback

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

    def get_one_tweak_from_inverted(self, data, start_index):
        """
        Given the current invertedTweak, return the current tweak data.
        """
        # XXX: This is called from set_internal.  Is it safe to query our values here?
        # XXX: Cache the forwards and inverted matrix list
        # XXX: Cache this data, and invalidate when the matrix list changes
        matrixes = self.get_matrixes(data)

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
        if idx < len(matrixes):
            offset *= matrixes[idx]

        return offset

    def get_tweak_array_from_inverted(self, data, builder):
        """
        Given the current invertedTweak, return the current tweak data.
        """
        # XXX: This is called from set_internal.  Is it safe to query our values here?
        # XXX: Cache the forwards and inverted matrix list
        # XXX: Cache this data, and invalidate when the matrix list changes
        matrixes = self.get_matrixes(data)

        invertedTweakData = data.inputArrayValue(self.attrInvertedTweak)

        for item in iterate_array_handle(invertedTweakData):
            thisValue = invertedTweakData.inputValue()

            idx = invertedTweakData.elementIndex()

            delta = thisValue.asFloat3()
            delta = OpenMaya.MVector(*delta)

            if idx < len(matrixes):
                delta *= matrixes[idx]

            element = builder.addElement(idx)
            element.set3Float(delta.x, delta.y, delta.z)

    def set_inverted_from_tweak(self, dataBlock, tweakData):
        matrixes = self.get_matrixes(dataBlock)

        outputInvertedTweak = dataBlock.outputArrayValue(self.attrInvertedTweak)
        builder = outputInvertedTweak.builder()

        for item in iterate_array_handle(tweakData):
            thisValue = tweakData.inputValue()

            idx = arrayCurrentIndex(tweakData)
            newElement = builder.addElement(idx)

            # log('%s' % tweakData)
            # index = tweakData.elementIndex()

            delta = thisValue.asFloat3()
            delta = OpenMaya.MVector(*delta)

            offset = delta
            if idx < len(matrixes):
                offset *= matrixes[idx]
            newElement.set3Float(*offset)

        outputInvertedTweak.set(builder)
        outputInvertedTweak.setAllClean()
        dataBlock.setClean(self.attrInvertedTweak)

    def deriveCurrentTweak(self):
        """
        Set .tweak from the current values of .invertedTweak and input matrixes.

        This is used when updating tweak for a new pose.
        """
        print 'derive'
#                handle = OpenMaya.MArrayDataHandle(handle)
#                print 'XXX main top'
#                builder = handle.builder()
#                values = self.get_tweak_array_from_inverted(data, builder)
#                handle.set(builder)

    def compute(self, plug, data):
#        print 'Compute: %s, %i, %i' % (plug.info(), plug.isElement(), plug.isChild())
        # We have to handle updating invertedTweak for both elements of the array and the
        # array itself, or things won't update reliably.
#        if plug.isChild() and plug.parent() == self.attrTweak:
#            print 'calc tweak child'
#            data.setClean(plug)
#            return

#        if plug == self.attrInvertedTweak:
#            print 'calc tweak'
#            data.setClean(plug)
#            return

#        if plug.isChild() and plug.parent() == self.attrInvertedTweak:
#            # log('Compute inverted')
#            tweakData = data.inputArrayValue(self.attrTweak)
#            self.set_inverted_from_tweak(data, tweakData)
#            # log('Done compute inverted')
#            return
#
#        if plug == self.attrInvertedTweak:
#            # log('Compute inverted outer')
#            tweakData = data.inputArrayValue(self.attrTweak)
#            self.set_inverted_from_tweak(data, tweakData)
#            # log('Done compute inverted outer')
#            return

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


#    def setInternalValueInContext(self, plug, handle, context):
#        try:
#            if plug == self.attrRecalculateTweak:
#                self.deriveCurrentTweak()
#        except Exception as e:
#            print 'setInternalValueInContext error: %s' % e
#            traceback.print_exc()
#
#        return super(testDeformer, self).setInternalValueInContext(plug, handle, context)

    def setInternalValueInContext(self, plug, handle, context):
        print 'set', plug.info(), plug.isElement(), plug.isChild()
        try:
            if plug.isChild() and plug.parent() == self.attrTweak:
                # This is setting .attrTweak[n].  Do we need to implement this?
                print 'Unhandled setting of %s' % plug.info()
                return

            if plug == self.attrTweak:
                print 'Set element', plug.info(), plug.isElement(), plug.isChild()
                if plug.isElement():
                    # This is setting ".attrTweak[n].x".  Do we need to implement this?
                    print 'Unhandled setting of %s' % plug.info()
                    return

                # Set the whole tweak array.  This is how manipulators set tweak data.
                handle = OpenMaya.MArrayDataHandle(handle)
                data = self._forceCache()
                self.set_inverted_from_tweak(data, handle)
                return
        except Exception as e:
            print 'setInternalValueInContext error: %s' % e
            traceback.print_exc()

        return super(testDeformer, self).setInternalValueInContext(plug, handle, context)

    def getInternalValueInContext(self, plug, handle, context):
        # Exceptions from this function tend to hard crash Maya.
        try:
#            print 'get', plug.info(), plug.isElement(), plug.isChild()
            # Shape nodes read the .tweak when modifying points, so they can change it and send us the
            # new tweak values.  Our native data is inverted tweak and we don't save tweak to disk, but
            # we do need to be able to calculate it based on .invertedTweak and the current pose so we
            # can give it to the shape node.
            if plug.isChild() and plug.parent() == self.attrTweak:
                # This is a request for a single dimension of .tweak, eg. .tweak[100].x.
                idx = plug.parent().logicalIndex()
                data = self._forceCache()
                value = self.get_one_tweak_from_inverted(data, start_index=idx)

                # XXX: This is a request for eg. .tweak[100].x.  What's the intended way to find out which
                # element this is?  The child plugs for k3float arrays are added implicitly and I can't
                # find the MObject representing them.
                def getChildIndex(plug):
                    parent = plug.parent()
                    for idx in xrange(parent.numChildren()):
                        child = parent.child(idx)
                        if plug == child:
                            return idx
                    return -1

                child_idx = getChildIndex(plug)
                if child_idx == -1:
                    print 'Unexpected plug %s' % plug.info()
                    return

                print 'Plug %s, idx %i, element %i, value %f' % (plug.info(), idx, child_idx, value[child_idx])
#                print '%s value: %f' % (plug.info(), value[child_idx])
                handle.setFloat(value[child_idx])
                return

            if plug == self.attrTweak:
                # This is one of:
                # .tweak
                # .tweak[100]
                data = self._forceCache()
                if plug.isElement():
                    idx = plug.logicalIndex()
                    value = self.get_one_tweak_from_inverted(data, start_index=idx)
                    print 'Plug %s, idx %i, value %f %f %f' % (plug.info(), idx, value.x, value.y, value.z)
                    handle.set3Float(value.x, value.y, value.z)
                    return

                # Someone queried .tweak itself, and not one of its elements.
                handle = OpenMaya.MArrayDataHandle(handle)
                print 'XXX main top'
                builder = handle.builder()
                values = self.get_tweak_array_from_inverted(data, builder)
                handle.set(builder)
                return

        except Exception as e:
            print 'getInternalValueInContext error: %s' % e
            traceback.print_exc()

        return super(testDeformer, self).getInternalValueInContext(plug, handle, context)

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
#    nAttr.setCached(False)
    nAttr.setStorable(False)
    nAttr.setInternal(True)
    testDeformer.addAttribute(testDeformer.attrTweak)
    # We don't actually need to declare that tweak affects invertedTweak, since this is
    # only ever set as a property, and never derived by compute().
#    testDeformer.attributeAffects(testDeformer.attrTweak, testDeformer.attrInvertedTweak)
    testDeformer.attributeAffects(testDeformer.attrTweak, outputGeom)

    # We don't use this directly.  It's used by updateInversion to remember where the base
    # mesh was when the deformer was initially created.
    testDeformer.aPosedMesh = tAttr.create('posedMesh', 'pm', OpenMaya.MFnData.kMesh)
    testDeformer.addAttribute(testDeformer.aPosedMesh)

    testDeformer.aMatrix = mAttr.create('inversionMatrix', 'im')
    mAttr.setArray(True)
    mAttr.setUsesArrayDataBuilder(True)
    testDeformer.addAttribute(testDeformer.aMatrix)
    testDeformer.attributeAffects(testDeformer.aMatrix, testDeformer.attrTweak)
    testDeformer.attributeAffects(testDeformer.aMatrix, outputGeom)

    # This is a hack: write to this attribute to force .tweak to be recalculated from
    # .invertedTweak.  We should use a command for this, but I can't find any way to
    # get our MPxDeformerNode instance from a command like you can natively.
    testDeformer.attrRecalculateTweak = nAttr.create('recalculateTweak', 'rct', OpenMaya.MFnNumericData.kBoolean)
    nAttr.setStorable(False)
    nAttr.setInternal(True)
    testDeformer.addAttribute(testDeformer.attrRecalculateTweak)


#class DeformerCommands(OpenMayaMPx.MPxCommand):
#    kPluginCmdName = 'testDeformer'
#    def doIt(self, args):
#        print 'go'
#        selectionList = OpenMaya.MSelectionList()
#        selectionList.add('testDeformer1')
#        plug = OpenMaya.MPlug()
#        selectionList.getPlug(0, plug)
#        print 'plug', plug
#
#        depNode = OpenMaya.MFnDependencyNode(plug.node())
#        userNode = depNode.userNode()
#        print userNode
#        print dir(userNode)
##        userNode.derive_current_tweak()
#
#    @staticmethod
#    def cmdCreator():
#        return OpenMayaMPx.asMPxPtr(DeformerCommands())

def initializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    
    plugin.registerNode(testDeformer.kPluginNodeName, testDeformer.kPluginNodeId, creator,
            initialize, OpenMayaMPx.MPxNode.kDeformerNode)
#    plugin.registerCommand(DeformerCommands.kPluginCmdName, DeformerCommands.cmdCreator)

def uninitializePlugin(mobject):
    plugin = OpenMayaMPx.MFnPlugin(mobject)
    plugin.deregisterNode(testDeformer.kPluginNodeId)
#    plugin.deregisterCommand(DeformerCommands.kPluginCmdName)
    

