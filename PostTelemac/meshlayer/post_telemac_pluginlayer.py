# -*- coding: utf-8 -*-
"""
/***************************************************************************
 PostTelemac
                                 A QGIS plugin
 Post Traitment or Telemac
                              -------------------
        begin                : 2015-07-07
        git sha              : $Format:%H$
        copyright            : (C) 2015 by Artelia
        email                : patrice.Verchere@arteliagroup.com
 ***************************************************************************/
 
 ***************************************************************************/
 Implementation of QgsPluginLayer class, used to show selafin res
 

 ***************************************************************************/
"""
# unicode behaviour
from __future__ import unicode_literals

# Standard import
import qgis.core
import qgis.gui
import qgis.utils

# Qt
from qgis.PyQt import QtCore

try:  # qt4
    from qgis.PyQt.QtGui import QApplication
except:  # qt5
    from qgis.PyQt.QtWidgets import QApplication

# other import
import collections
import time
import gc
import os

# local import
from ..meshlayerdialogs.posttelemacpropertiesdialog import PostTelemacPropertiesDialog
from ..meshlayerrenderer.meshlayer_rubberband import MeshLayerRubberband
from ..meshlayerrenderer.post_telemac_pluginlayer_renderer import PostTelemacPluginLayerRenderer
import sys

# from ..meshlayerlibs.tri import LinearTriInterpolator

"""
Global variable for making new graphs (matplotlib)  with maplotlib 
fig 0 : ??
fig 1 : ??
Concept : when creating new SelafinPluginLayer, use 
selafininstancecount for pluginlayer-draw, 
selafininstancecount + 1 for graph temp util,
 selafininstancecount + 2 for flow util
  selafininstancecount + 3 for volume util
"""
selafininstancecount = 2


class SelafinPluginLayer(qgis.core.QgsPluginLayer):
    """
    QgsPluginLayer implementation for drawing selafin file results
    """

    CRS = qgis.core.QgsCoordinateReferenceSystem()
    LAYER_TYPE = "selafin_viewer"
    timechanged = QtCore.pyqtSignal(int)
    updatevalue = QtCore.pyqtSignal(int)

    def __init__(self, nom1=None, specificmapcanvas=None):
        """
        Init method : 
            initialize variables, connect qgis signals
            load PostTelemacPropertiesDialog class related to this SelafinPluginLayer
            load Selafin2QImage class wich is called to create the qimage needed to draw
        """
        qgis.core.QgsPluginLayer.__init__(self, SelafinPluginLayer.LAYER_TYPE, nom1)

        # global variable init
        global selafininstancecount
        self.instancecount = int(selafininstancecount)

        self.meshrenderer = None  # the class used to get qimage for canvas or composer
        self.renderer = None  # the qgis renderer class
        self.setValid(True)
        self.realCRS = qgis.core.QgsCoordinateReferenceSystem()
        self.xform = None  # transformation class for reprojection

        # selafin file - properties
        self.hydraufilepath = None  # selafin file name
        self.parametrestoload = {
            "virtual_parameters": [],
            "xtranslation": 0.0,
            "ytranslation": 0.0,
            "renderer": None,
        }  # virtual parameters to load with projet

        self.param_displayed = None  # temp parameter of selafin file
        self.time_displayed = None  # time for displaying of selafin file
        self.values = None  # Values of params for time t
        self.value = None  # Values of param_gachette for time t

        # managers
        self.hydrauparser = None  # The dataprovider
        self.rubberband = MeshLayerRubberband(self)  # class used for rubberband

        # properties dialog
        if specificmapcanvas is None:
            self.canvas = qgis.utils.iface.mapCanvas()
        else:
            self.canvas = specificmapcanvas

        self.propertiesdialog = PostTelemacPropertiesDialog(self)

        # viewer parameters
        self.propertiesdialog.tabWidget_lvl_vel.setCurrentIndex(0)
        self.propertiesdialog.color_palette_changed(0, type="contour")
        self.propertiesdialog.color_palette_changed(0, type="velocity")

        self.affichagevitesse = False
        self.forcerefresh = False
        self.showmesh = False
        self.showvelocityparams = {"show": False, "type": None, "step": None, "norm": None}

        self.propertiesdialog.tabWidget_lvl_vel.setCurrentIndex(0)
        self.propertiesdialog.color_palette_changed(0)
        self.propertiesdialog.tabWidget_lvl_vel.setCurrentIndex(1)
        self.propertiesdialog.color_palette_changed(0)
        self.propertiesdialog.tabWidget_lvl_vel.setCurrentIndex(0)

        # levels
        self.levels = [self.propertiesdialog.predeflevels[i][1] for i in range(len(self.propertiesdialog.predeflevels))]
        """
        #Add 4 to global variable : 
            figure (selafininstancecount) used for get_image, 
            figure(selafininstancecount + 1) for graphtemp, 
            figure(selafininstancecount +2) for graph flow
            figure(selafininstancecount +3) for graph volume
            figure(selafininstancecount +4) for flow computation
        """
        selafininstancecount = selafininstancecount + 5

        self.draw = True

        # Connectors
        self.canvas.destinationCrsChanged.connect(self.changecrs)
        # to close properties dialog when layer deleted
        try:  # qgis2
            qgis.core.QgsMapLayerRegistry.instance().layersWillBeRemoved["QStringList"].connect(self.RemoveScenario)
        except:  # qgis3
            qgis.core.QgsProject.instance().layersWillBeRemoved["QStringList"].connect(self.RemoveScenario)

        self.updatevalue.connect(self.updateSelafinValues)

        # load parsers
        self.parsers = []  # list of parser classes
        self.loadParsers()

    # ****************************************************************************************************
    # ************* Typical plugin layer methods***********************************************************
    # ****************************************************************************************************

    def clone(self):
        return None

    def createMapRenderer(self, renderercontext):
        self.renderer = PostTelemacPluginLayerRenderer(self, renderercontext)
        return self.renderer

    def pluginLayerType(self):
        return self.LAYER_TYPE

    def loadParsers(self):
        import glob, inspect, importlib
        import PostTelemac.meshlayerparsers

        # import PostTelemac.meshlayerparsers, sys
        self.parsers = []
        path = os.path.join(os.path.dirname(__file__), "..", "meshlayerparsers")
        modules = glob.glob(path + "/*.py")
        __all__ = [os.path.basename(f)[:-3] for f in modules if os.path.isfile(f)]
        for x in __all__:
            moduletemp = importlib.import_module("." + x, "PostTelemac.meshlayerparsers")
            for name, obj in inspect.getmembers(moduletemp, inspect.isclass):
                try:
                    self.parsers.append([obj, obj.SOFTWARE, obj.EXTENSION])
                except Exception as e:
                    pass

        # reorder list for havin telemac in first
        templistofsoftware = [par[1] for par in self.parsers]
        telemacindex = templistofsoftware.index("TELEMAC")
        self.parsers.insert(0, self.parsers.pop(telemacindex))
        self.parsers.append([None, "Other extension", "*"])

    def extent(self):
        """ 
        implementation of method from QgsMapLayer to compute the extent of the layer 
        return QgsRectangle()
        """
        if self.hydrauparser is not None and self.hydrauparser.path is not None:
            rect = self.hydrauparser.extent()
            return self.xform.transformBoundingBox(rect)
        else:
            return qgis.core.QgsRectangle()

    def legendSymbologyItems(self, iconsize):
        """ 
        implementation of method from QgsPluginLayer to show legend entries (in QGIS >= 2.1) 
        return an array with [name of symbology, qpixmap]
        """
        if self.meshrenderer is not None:
            lst = self.meshrenderer.colormanager.generateSymbologyItems(iconsize)
            return lst
        else:
            return []

    # Not used yet
    def readSymbology(self, node, err):
        """ Called when copy symbology is activated"""
        return False

    def writeSymbology(self, node, doc, err):
        """ Called when past symbology is activated"""
        return False

    # ****************************************************************************************************
    # Initialise methods *********************************************************************
    # ****************************************************************************************************

    def load_selafin(self, hydraufilepath=None, filetype=None):
        """
        Handler called when 'choose file' is clicked
        Load Selafin file and initialize properties dialog
        """

        try:
            self.hydrauparser.emitMessage.disconnect(self.propertiesdialog.errorMessage)
        except Exception as e:
            pass

        self.hydraufilepath = hydraufilepath
        # Update name in symbology
        filenametemp = os.path.basename(self.hydraufilepath)
        nom, extension = os.path.splitext(filenametemp)
        try:  # qgis2
            self.setLayerName(nom)
        except:  # qgis3
            self.setName(nom)

        # Set parser
        if (filetype is not None) and (filetype in [elem[1] for elem in self.parsers]):
            for i, elem in enumerate(self.parsers):
                if elem[1] == filetype:
                    self.hydrauparser = elem[0](self.parametrestoload)
                    break
        else:
            self.propertiesdialog.combodialog.loadValues([pars[1] for pars in self.parsers])
            self.propertiesdialog.combodialog.label.setText(
                "File type not found - please tell me what type of file you are loading : "
            )
            if self.propertiesdialog.combodialog.exec_():
                self.hydrauparser = self.parsers[self.propertiesdialog.combodialog.combobox.currentIndex()][0](
                    self.parametrestoload
                )
                filetype = self.parsers[self.propertiesdialog.combodialog.combobox.currentIndex()][1]
            else:
                return False
        self.hydrauparser.loadHydrauFile(self.hydraufilepath)
        self.propertiesdialog.groupBox_Title.setTitle(filetype + " file")
        self.propertiesdialog.loadTools(filetype)
        self.propertiesdialog.updateWithParserParamsIdentified()
        self.hydrauparser.emitMessage.connect(self.propertiesdialog.errorMessage)

        if qgis.utils.iface is None:
            print("************ RENDERER ********************* ")

        # create renderer
        if QtCore.QSettings().value("posttelemac/renderlib") is not None:
            if QtCore.QSettings().value("posttelemac/renderlib") == "OpenGL":
                if int(qgis.PyQt.QtCore.QT_VERSION_STR[0]) == 4:
                    if qgis.utils.iface is None:
                        print("OPENGL Qt4 renderer")
                    from ..meshlayerrenderer.post_telemac_opengl_get_qimage import MeshRenderer
                elif int(qgis.PyQt.QtCore.QT_VERSION_STR[0]) == 5:
                    if qgis.utils.iface is None:
                        print("OPENGL Qt5 renderer")
                    from ..meshlayerrenderer.post_telemac_opengl_get_qimage_qt5 import MeshRenderer

            elif QtCore.QSettings().value("posttelemac/renderlib") == "MatPlotLib":
                from ..meshlayerrenderer.post_telemac_matplotlib_get_qimage import MeshRenderer
        else:
            if sys.version_info.major == 2:
                from ..meshlayerrenderer.post_telemac_opengl_get_qimage import MeshRenderer
            elif sys.version_info.major == 3:
                from ..meshlayerrenderer.post_telemac_opengl_get_qimage_qt5 import MeshRenderer

        self.meshrenderer = MeshRenderer(self, self.instancecount)

        # reinitialize layer's render parameters
        if not self.param_displayed:
            self.param_displayed = 0
        if not self.meshrenderer.lvl_contour:
            self.meshrenderer.lvl_contour = self.levels[0]
        if not self.meshrenderer.lvl_vel:
            self.meshrenderer.lvl_vel = self.levels[0]
        if not self.time_displayed:
            self.time_displayed = 0
        if not self.meshrenderer.alpha_displayed:
            self.meshrenderer.alpha_displayed = self.parametrestoload["renderer_alpha"]

        # initialise selafin crs
        if self.crs().authid() == "":
            self.setRealCrs(self.canvas.mapSettings().destinationCrs())
            if sys.version_info.major == 2:
                self.xform = qgis.core.QgsCoordinateTransform(self.realCRS, self.canvas.mapSettings().destinationCrs())
            elif sys.version_info.major == 3:
                self.xform = qgis.core.QgsCoordinateTransform(
                    self.realCRS, self.canvas.mapSettings().destinationCrs(), qgis.core.QgsProject.instance()
                )
        self.meshrenderer.changeTriangulationCRS()
        # update selafin values
        self.updateSelafinValuesEmit()

        # Update propertiesdialog
        self.propertiesdialog.update()

        # Apply renderer

        if self.propertiesdialog.comboBox_levelstype.currentIndex() == 0:
            self.propertiesdialog.color_palette_changed(type="contour")  # initialize colors in renderer
            self.propertiesdialog.color_palette_changed(type="velocity")  # initialize colors in renderer
            self.meshrenderer.change_lvl_contour(self.meshrenderer.lvl_contour)
            self.meshrenderer.change_lvl_vel(self.meshrenderer.lvl_vel)

        elif self.propertiesdialog.comboBox_levelstype.currentIndex() == 1:
            self.propertiesdialog.createstepclass()
            self.propertiesdialog.color_palette_changed(type="contour")  # initialize colors in renderer

        elif self.propertiesdialog.comboBox_levelstype.currentIndex() == 2:
            self.propertiesdialog.loadMapRamp(self.parametrestoload["renderer"][3])

        """
        if int(element.attribute('level_type')) == 0:
            self.propertiesdialog.change_cmchoosergenericlvl()
        elif int(element.attribute('level_type')) == 1:
            self.propertiesdialog.createstepclass()
        """

        # reset parametrestoload
        self.parametrestoload["renderer"] = None

        """
        # change colors
        self.propertiesdialog.color_palette_changed(type='contour')  # initialize colors in renderer
        self.propertiesdialog.color_palette_changed(type='velocity')  # initialize colors in renderer

        # change levels
        self.meshrenderer.change_lvl_contour(self.meshrenderer.lvl_contour)
        self.meshrenderer.change_lvl_vel(self.meshrenderer.lvl_vel)
        """

        # final update
        self.triggerRepaint()

        if qgis.utils.iface is not None:
            try:  # qgis2
                qgis.utils.iface.legendInterface().refreshLayerSymbology(self)
            except:  # qgis3
                qgis.utils.iface.layerTreeView().refreshLayerSymbology(self.id())

        self.canvas.setExtent(self.extent())

        return True

    def clearParameters(self):
        self.param_displayed = None
        self.time_displayed = None
        if self.meshrenderer is not None:
            self.meshrenderer.alpha_displayed = 100.0
            self.meshrenderer.lvl_contour = None

    # ****************************************************************************************************
    # Update method - selafin value - used with compare util  *********************************
    # ****************************************************************************************************

    def updateSelafinValuesEmit(self, onlyparamtimeunchanged=-1):
        """
        Updates the values stored in self.values and self.value
        called when loading selafin file, or when selafin's time is changed
        It emits a signal, because this method is redirected to a different method in comparetool  
        when tool "compare" is activated
        """
        self.hydrauparser.identifyKeysParameters()
        self.updatevalue.emit(onlyparamtimeunchanged)

    def updateSelafinValues(self, onlyparamtimeunchanged=-1):
        """
        Updates the values stored in self.values and self.value
        called when loading selfin file, or when selafin's time is changed
        """
        DEBUG = False

        if DEBUG:
            self.debugtext = []
            self.timestart = time.clock()

        if onlyparamtimeunchanged < 0:
            # self.triinterp = None
            self.hydrauparser.interpolator = None
            self.values = self.hydrauparser.getValues(self.time_displayed)
            if DEBUG:
                self.debugtext += ["values : " + str(round(time.clock() - self.timestart, 3))]
            self.value = self.values[self.param_displayed]
        else:
            self.value = self.values[self.param_displayed]

        if DEBUG:
            self.debugtext += ["value : " + str(round(time.clock() - self.timestart, 3))]
        if DEBUG:
            self.propertiesdialog.textBrowser_2.append(str(self.debugtext))

    # ****************************************************************************************************
    # Change variables                                                  *********************************
    # ****************************************************************************************************

    def changeTime(self, nb):
        """When changing time value to display"""
        self.time_displayed = nb
        self.updateSelafinValuesEmit()
        # self.triinterp = None
        self.hydrauparser.interpolator = None
        self.timechanged.emit(nb)
        if self.draw:
            self.triggerRepaint()

    def changeParam(self, int1):
        """When changing parameter value for display"""
        self.param_displayed = int1
        self.updateSelafinValuesEmit(int1)
        if qgis.utils.iface is not None:
            try:  # qgis2
                qgis.utils.iface.legendInterface().refreshLayerSymbology(self)
            except:  # qgis3
                qgis.utils.iface.layerTreeView().refreshLayerSymbology(self.id())
        self.forcerefresh = True
        self.triggerRepaint()

    def setRealCrs(self, qgscoordinatereferencesystem):
        """
        The real crs of layer is saved in realCRS variable.
        Otherwise (if real crs is saved in CRS variable), reprojection of the qimage is not fully working. 
        So the layer.crs is the same as the canvas.crs, and reprojection is done in meshrenderer using layer.realCRS
        """
        self.realCRS = qgscoordinatereferencesystem
        if False:
            self.setCrs(qgis.utils.iface.mapCanvas().mapSettings().destinationCrs())
            self.xform = qgis.core.QgsCoordinateTransform(
                self.realCRS, qgis.utils.iface.mapCanvas().mapSettings().destinationCrs()
            )
        if True:
            self.setCrs(self.canvas.mapSettings().destinationCrs())
            if sys.version_info.major == 2:
                self.xform = qgis.core.QgsCoordinateTransform(self.realCRS, self.canvas.mapSettings().destinationCrs())
            elif sys.version_info.major == 3:
                self.xform = qgis.core.QgsCoordinateTransform(
                    self.realCRS, self.canvas.mapSettings().destinationCrs(), qgis.core.QgsProject.instance()
                )

        if self.meshrenderer is not None:
            self.meshrenderer.changeTriangulationCRS()
        self.forcerefresh = True
        self.triggerRepaint()

    def crs(self):
        """
        implement crs method to get the real CRS
        """
        return self.realCRS

    def changecrs(self):
        """Associated with mapcanvascrschaned slot and changing layer crs in property dialog"""
        try:
            if False:
                self.setCrs(qgis.utils.iface.mapCanvas().mapSettings().destinationCrs())
                self.xform = qgis.core.QgsCoordinateTransform(
                    self.realCRS, qgis.utils.iface.mapCanvas().mapSettings().destinationCrs()
                )

            if True:
                self.setCrs(self.canvas.mapSettings().destinationCrs())
                self.xform = qgis.core.QgsCoordinateTransform(self.realCRS, self.canvas.mapSettings().destinationCrs())
            self.meshrenderer.changeTriangulationCRS()
            self.forcerefresh = True
            self.triggerRepaint()
        except Exception as e:
            pass

    # ****************************************************************************************************
    # show velocity, mesh  *********************************
    # ****************************************************************************************************

    def showVelocity(self):
        """
        Called when PostTelemacPropertiesDialog 's "plot velocity" checkbox is checked
        """
        self.forcerefresh = True
        if qgis.utils.iface is not None:
            try:  # qgis2
                qgis.utils.iface.legendInterface().refreshLayerSymbology(self)
            except:  # qgis3
                # self.propertiesdialog.errorMessage('plugin layer - legend failed')
                qgis.utils.iface.layerTreeView().refreshLayerSymbology(self.id())
        self.triggerRepaint()

    def showMesh(self, int1):
        """
        Called when PostTelemacPropertiesDialog 's "plot mesh" checkbox is checked
        """
        if int1 == 2:
            self.showmesh = True
        elif int1 == 0:
            self.showmesh = False
        self.triggerRepaint()
        self.forcerefresh = True
        self.triggerRepaint()

    # ****************************************************************************************************
    # method for profile tool  *********************************
    # ****************************************************************************************************

    def name(self):
        if self.hydraufilepath is not None:
            return os.path.basename(self.hydraufilepath).split(".")[0]
        else:
            return "Empty PostTelemac pluginlayer"

    def bandCount(self):
        return len(self.hydrauparser.parametres)

    def rasterUnitsPerPixel(self):
        # Only required so far for the profile tool
        # There's probably a better way of doing this
        return float(0.5)

    def rasterUnitsPerPixelX(self):
        # Only required so far for the profile tool
        return self.rasterUnitsPerPixel()

    def rasterUnitsPerPixelY(self):
        # Only required so far for the profile tool
        return self.rasterUnitsPerPixel()

    # ****************************************************************************************************
    # method for identifying value  *********************************
    # ****************************************************************************************************

    def identify(self, qgspointfromcanvas, multiparam=False):
        """
        Called by profile tool plugin
        compute value of selafin parameters at point qgspoint
        return tuple with (success,  dictionnary with {parameter : value} )
        """
        qgspointfromcanvas = self.xform.transform(qgspointfromcanvas, qgis.core.QgsCoordinateTransform.ReverseTransform)
        if self.hydrauparser.interpolator is None:
            success = self.hydrauparser.updateInterpolatorEmit(self.time_displayed)
        else:
            success = True

        # getvalues
        d = collections.OrderedDict()
        if success:
            try:
                # v= [float(self.triinterp[i].__call__([qgspointfromcanvas.x()],[qgspointfromcanvas.y()])) for i in range(len(self.hydrauparser.parametres))]
                v = [
                    float(
                        self.hydrauparser.interpolator[i].__call__([qgspointfromcanvas.x()], [qgspointfromcanvas.y()])
                    )
                    for i in range(len(self.hydrauparser.parametres))
                ]

            except Exception as e:
                v = None
            # send results
            for param in self.hydrauparser.parametres:
                try:
                    d[QtCore.QString(param[1])] = v[param[0]]
                except:
                    d[param[1]] = v[param[0]]
            return (True, d)
        else:
            return (False, d)

    # ****************************************************************************************************
    # ************Method for saving/loading project with selafinlayer file***********************************
    # ****************************************************************************************************

    def readXml(self, node, context):
        """
        implementation of method from QgsMapLayer to load layer from qgsproject
        return True ifsuccessful
        """
        element = node.toElement()
        prj = qgis.core.QgsProject.instance()
        hydraufilepath = prj.readPath(element.attribute("meshfile"))

        if os.path.isfile(hydraufilepath):
            self.setRealCrs(qgis.core.QgsCoordinateReferenceSystem(prj.readPath(element.attribute("crs"))))
            self.param_displayed = int(element.attribute("parametre"))
            # self.meshrenderer.alpha_displayed = int(element.attribute('alpha'))
            self.parametrestoload["renderer_alpha"] = int(element.attribute("alpha"))
            self.time_displayed = int(element.attribute("time"))
            self.showmesh = int(element.attribute("showmesh"))
            self.propertiesdialog.checkBox_showmesh.setChecked(self.showmesh)

            # levelthings - old - need to reworked
            if False:
                try:
                    self.propertiesdialog.comboBox_genericlevels.setCurrentIndex(int(element.attribute("level_value")))
                    lvlstep = [
                        element.attribute("level_step").split(";")[i]
                        for i in range(len(element.attribute("level_step").split(";")))
                    ]
                    self.propertiesdialog.lineEdit_levelmin.setText(lvlstep[0])
                    self.propertiesdialog.lineEdit_levelmax.setText(lvlstep[1])
                    self.propertiesdialog.lineEdit_levelstep.setText(lvlstep[2])
                    self.propertiesdialog.comboBox_clrgame.setCurrentIndex(int(element.attribute("level_color")))

                    self.propertiesdialog.comboBox_levelstype.setCurrentIndex(int(element.attribute("level_type")))
                    if int(element.attribute("level_type")) == 0:
                        self.propertiesdialog.change_cmchoosergenericlvl()
                    elif int(element.attribute("level_type")) == 1:
                        self.propertiesdialog.createstepclass()
                except:
                    pass
            if True:
                try:
                    self.parametrestoload["renderer"] = [
                        int(element.attribute("level_type")),  # the type of renderer (defined,range,user)
                        [
                            int(element.attribute("level_preset_color")),
                            int(element.attribute("level_preset_value")),
                        ],  # preset params
                        [
                            int(element.attribute("level_range_color")),
                            element.attribute("level_range_step").split(";"),
                        ],  # range params
                        element.attribute("level_user_name"),
                    ]  # user params
                except Exception as e:
                    print("error renderer", e)
            """
            #velocity things
            self.propertiesdialog.comboBox_genericlevels_2.setCurrentIndex(0)
            self.propertiesdialog.comboBox_clrgame_2.setCurrentIndex(0)
            self.propertiesdialog.change_cmchoosergenericlvl_vel()
            """
            # Virtual param things
            strtemp = element.attribute("virtual_param").split(";")
            count = int((len(strtemp) - 1) / 3)
            for i in range(count):
                self.parametrestoload["virtual_parameters"].append(
                    [i, strtemp[3 * i], int(strtemp[3 * i + 1]), strtemp[3 * i + 2]]
                )

            try:
                self.parametrestoload["xtranslation"] = float(element.attribute("xtranslation"))
                self.parametrestoload["ytranslation"] = float(element.attribute("ytranslation"))
            except Exception as e:
                pass

            self.load_selafin(hydraufilepath, element.attribute("filetype"))
            return True
        else:
            return False

    def writeXml(self, node, doc, context):
        """
        implementation of method from QgsMapLayer to save layer in  qgsproject
        return True ifsuccessful
        """
        prj = qgis.core.QgsProject.instance()
        element = node.toElement()
        element.setAttribute("filetype", self.hydrauparser.SOFTWARE)
        element.setAttribute("crs", self.realCRS.authid())
        element.setAttribute("type", "plugin")
        element.setAttribute("name", SelafinPluginLayer.LAYER_TYPE)
        element.setAttribute("meshfile", prj.writePath(self.hydraufilepath))
        element.setAttribute("parametre", self.param_displayed)
        element.setAttribute("alpha", self.meshrenderer.alpha_displayed)
        element.setAttribute("time", self.time_displayed)
        element.setAttribute("showmesh", int(self.showmesh))
        # levelthings - old - need to reworked
        self.propertiesdialog.tabWidget_lvl_vel.setCurrentIndex(0)
        element.setAttribute("level_type", self.propertiesdialog.comboBox_levelstype.currentIndex())
        # Preset
        element.setAttribute("level_preset_color", self.propertiesdialog.comboBox_clrgame.currentIndex())
        element.setAttribute("level_preset_value", self.propertiesdialog.comboBox_genericlevels.currentIndex())
        # range
        element.setAttribute("level_range_color", self.propertiesdialog.comboBox_clrgame2.currentIndex())
        element.setAttribute(
            "level_range_step",
            self.propertiesdialog.lineEdit_levelmin.text()
            + ";"
            + self.propertiesdialog.lineEdit_levelmax.text()
            + ";"
            + self.propertiesdialog.lineEdit_levelstep.text(),
        )
        # user
        element.setAttribute("level_user_name", self.propertiesdialog.comboBox_clrramp_preset.currentText())
        # translation
        element.setAttribute("xtranslation", self.hydrauparser.translatex)
        element.setAttribute("ytranslation", self.hydrauparser.translatey)
        # Virtuall param things
        strtrmp = ""
        for param in self.hydrauparser.parametres:
            if param[4]:
                strtrmp += param[1] + ";" + str(param[2]) + ";" + param[4] + ";"
        element.setAttribute("virtual_param", strtrmp)

        return True

    # ****************************************************************************************************
    # ************Called when the layer is deleted from qgis canvas ***********************************
    # ****************************************************************************************************

    def RemoveScenario(self, string1):
        """
        When deleting a selafin layer - remove : 
            matplotlib ' s figures
            propertiesdialog 
            and other things
        """
        self.propertiesdialog.tabWidget.setCurrentIndex(0)

        if str(self.id()) in string1:
            # closing figures
            """
            if self.propertiesdialog.unloadtools :
                try:
                    self.propertiesdialog.figure1.clf()
                    matplotlib.pyplot.close(self.propertiesdialog.figure1)
                except Exception as e :
                    print('fig1 ' + str(e) )
            if self.propertiesdialog.unloadtools :
                try:
                    self.propertiesdialog.figure2.clf()
                    matplotlib.pyplot.close(self.propertiesdialog.figure2) 
                except Exception as e :
                    print('fig2 ' + str(e))
            if self.propertiesdialog.unloadtools :
                try:
                    self.propertiesdialog.figure3.clf()
                    matplotlib.pyplot.close(self.propertiesdialog.figure3) 
                except Exception as e :
                    print('fig3 ' + str(e))
                    
            if not self.propertiesdialog.unloadtools :
                for tool in self.propertiesdialog.tools :
                    try:
                        tool.figure1.clf()
                        matplotlib.pyplot.close(tool.figure1) 
                    except Exception as e :
                        #print 'closing figure ' + str(e)
                        pass
            """

            """
            #if self.rendertype == 'Matplotlib' :
            if self.meshrenderer != None and self.meshrenderer.RENDERER_TYPE == 'MatPlotLib' :
                try:
                    self.meshrenderer.fig.clf()
                    matplotlib.pyplot.close(self.meshrenderer.fig)
                except Exception as e :
                    print('fig ' + str(e))
            """
            if self.hydrauparser is not None:
                self.hydrauparser.hydraufile = None

            if self.hydrauparser is None:
                try:
                    self.hydrauparser.emitMessage.disconnect(self.propertiesdialog.errorMessage)
                except Exception as e:
                    pass
                del self.hydrauparser

            if QtCore.QSettings().value("posttelemac/renderlib") is None:
                self.propertiesdialog.changeMeshLayerRenderer(self.propertiesdialog.comboBox_rendertype.currentIndex())
            # self.propertiesdialog.postutils.rubberband.reset()
            # self.propertiesdialog.postutils.rubberbandpoint.reset()
            # closing properties dialog
            self.propertiesdialog.unloadTools()
            self.propertiesdialog.close()
            del self.propertiesdialog
            # closing some stuff - do not succeed in retrieving what does not release memory...
            del self.values
            del self.value
            del self.meshrenderer

            # end : garbage collector
            gc.collect()
            # close connexions
            # qgis.core.QgsMapLayerRegistry.instance().layersWillBeRemoved.disconnect(self.RemoveScenario)

            # to close properties dialog when layer deleted
            try:
                qgis.core.QgsMapLayerRegistry.instance().layersWillBeRemoved.disconnect(self.RemoveScenario)
            except:
                qgis.core.QgsProject.instance().layersWillBeRemoved.disconnect(self.RemoveScenario)
            self.canvas.destinationCrsChanged.disconnect(self.changecrs)

    # ****************************************************************************************************
    # ************translation                                        ***********************************
    # ****************************************************************************************************

    def tr(self, message):
        """Used for translation"""
        if False:
            try:
                return QtCore.QCoreApplication.translate("SelafinPluginLayer", message, None, QApplication.UnicodeUTF8)
            except Exception as e:
                return message
        if True:
            return message

    def setTransformContext(self, transformContext):
        pass
