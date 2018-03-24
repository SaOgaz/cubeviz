import os
import yaml
import warnings

from qtpy.QtCore import Qt, Signal, QThread
from qtpy.QtWidgets import (
    QDialog, QApplication, QPushButton, QProgressBar,
    QLabel, QWidget, QDockWidget, QHBoxLayout, QVBoxLayout,
    QComboBox, QMessageBox, QLineEdit, QRadioButton, QWidgetItem, QSpacerItem
)

from glue.utils.qt import update_combobox

from astropy.utils.exceptions import AstropyWarning
from astropy import units as u
from specviz.third_party.glue.data_viewer import dispatch as specviz_dispatch

OBS_WAVELENGTH_TEXT = 'Obs Wavelength'
REST_WAVELENGTH_TEXT = 'Rest Wavelength'

DEFAULT_FLUX_UNITS_CONFIGS = os.path.join(os.path.dirname(__file__), 'registered_flux_units.yaml')


class UnitController:
    def __init__(self, cubeviz_layout):
        self._cv_layout = cubeviz_layout
        ui = cubeviz_layout.ui
        self._original_wavelengths = self._cv_layout._wavelengths
        self._new_wavelengths = []
        self._original_units = u.m
        self._new_units = self._original_units
        self._wcs = None

        # Add the redshift z value
        self._redshift_z = 0

        # This is the Wavelength conversion/combobox code
        self._units = [u.m, u.cm, u.mm, u.um, u.nm, u.AA]
        self._units_titles = list(u.long_names[0].title() for u in self._units)

        # This is the label for the wavelength units
        self._wavelength_textbox_label = ui.wavelength_textbox_label.text()

        specviz_dispatch.setup(self)

    @property
    def wavelength_label(self):
        return self._wavelength_textbox_label

    @wavelength_label.setter
    def wavelength_label(self, value):
        self._wavelength_textbox_label = value

    @property
    def units(self):
        return self._units

    @property
    def unit_titles(self):
        return self._units_titles

    @property
    def redshift_z(self):
        """
        Get the Z value for the redshift.

        :return: Z redshift value
        """
        return self._redshift_z

    @redshift_z.setter
    def redshift_z(self, new_z):
        """
        Set the new Z value for the redshift.

        :return: Z redshift value
        """

        # We want to make sure there is no odd messaging looping that might
        # happen if we receive the same value. In this case, we are done.
        if self._redshift_z == new_z:
            return

        self._redshift_z = new_z

        if new_z is not None and new_z > 0:
            # Set the label
            self._wavelength_textbox_label = REST_WAVELENGTH_TEXT
            self._cv_layout._slice_controller.wavelength_label = REST_WAVELENGTH_TEXT
            self._cv_layout.set_wavelengths((1+new_z)*self._original_wavelengths, self._new_units)
        else:
            # Set the label
            self._wavelength_textbox_label = OBS_WAVELENGTH_TEXT
            self._cv_layout._slice_controller.wavelength_label = OBS_WAVELENGTH_TEXT
            self._cv_layout.set_wavelengths(self._original_wavelengths, self._new_units)

        # Calculate and set the new wavelengths
        self._wavelengths = self._original_wavelengths / (1 + self._redshift_z)

        # Send them to the slice controller
        self._cv_layout._slice_controller.set_wavelengths(self._wavelengths, self._new_units)

        # Send the redshift value to specviz
        specviz_dispatch.change_redshift.emit(redshift=self._redshift_z)

    @specviz_dispatch.register_listener("change_redshift")
    def change_redshift(self, redshift):
        """
        Change the redshift based on a message from specviz.

        :paramter: redshift - the Z value.
        :return: nothing
        """
        if self._redshift_z == redshift:
            # If the input redshift is the current value we have
            # then we are not going to do anything.
            return
        else:
            # This calls the setter above, so really, the magic is there.
            self.redshift_z = redshift

    def on_combobox_change(self, new_unit_name):
        """
        Callback for change in unitcombobox value
        :param event:
        :return:
        """
        # Get the new unit name from the selected value in the comboBox and
        # set that as the new unit that wavelengths will be converted to
        # new_unit_name = self._wavelength_combobox.currentText()
        self._new_units = self._units[self._units_titles.index(new_unit_name)]

        self._new_wavelengths = self.convert_wavelengths(self._original_wavelengths, self._original_units, self._new_units)
        if self._new_wavelengths is None:
            return

        # Set layout._wavelength as the new wavelength
        self._cv_layout.set_wavelengths(self._new_wavelengths, self._new_units)

    def convert_wavelengths(self, old_wavelengths, old_units, new_units):
        if old_wavelengths is not None:
            new_wavelengths = ((old_wavelengths * old_units).to(new_units) / new_units)
            return new_wavelengths
        return False

    def enable(self, wcs, wavelength):
        self._original_wavelengths = wavelength
        self._wcs = wcs

    def get_new_units(self):
        return self._new_units


class FluxUnitRegistry:
    def __init__(self):
        self.runtime_defined_units = []

    @staticmethod
    def _locally_defined_units():
        units = [u.uJy, u.mJy, u.Jy,
                 u.erg / u.cm ** 2 / u.s / u.Hz,
                 u.erg / u.cm ** 2 / u.s / u.um,
                 u.erg / u.cm ** 2 / u.s]
        return units

    @staticmethod
    def _equivalencies_defined_units():
        equivalencies = u.spectral_density(3500 * u.AA)
        units = []
        for unit1, unit2, converter1, converter2 in equivalencies:
            if 'spectral flux density' in unit1.physical_type:
                units.append(unit1)
            if 'spectral flux density' in unit2.physical_type:
                units.append(unit2)
        return units

    def get_unit_list(self):
        item_list = []
        item_list.extend(self._equivalencies_defined_units())
        item_list.extend(self._locally_defined_units())
        item_list.extend(self.runtime_defined_units)

        unit_list = []
        for item in item_list:
            if isinstance(item, str):
                unit_list.append(item)
            elif isinstance(item, u.UnitBase):
                unit_list.append(item.to_string())
        unit_list = list(set(unit_list))
        return sorted(unit_list)

    def add_unit(self, item):
        if isinstance(item, str) \
                or isinstance(item, u.UnitBase):
            if item not in self.runtime_defined_units:
                self.runtime_defined_units.append(item)


class AreaUnitRegistry:
    def __init__(self):
        self.runtime_solid_angle_units = []
        self.runtime_pixel_units = []

    @staticmethod
    def _locally_defined_solid_angle_units():
        units = []
        return units

    @staticmethod
    def _locally_defined_pixel_units():
        units = []

        spaxel = u.def_unit('spaxel', u.astrophys.pix)
        u.add_enabled_units(spaxel)
        units.append(spaxel)

        return units

    @staticmethod
    def _astropy_derived_solid_angle_units():
        angle_units = u.degree.find_equivalent_units()
        units = []
        for unit in angle_units:
            unit = unit**2
            units.append(unit)
        return units

    @staticmethod
    def _astropy_defined_solid_angle_units():
        return [u.steradian]

    @staticmethod
    def _pixel_units():
        return [u.pix]

    def get_unit_list(self, pixel_only=False, solid_angle_only=False):
        item_list = []
        if not solid_angle_only:
            item_list.extend(self.runtime_pixel_units)
            item_list.extend(self._locally_defined_pixel_units())
            item_list.extend(self._pixel_units())
        if not pixel_only:
            item_list.extend(self.runtime_solid_angle_units)
            item_list.extend(self._locally_defined_solid_angle_units())
            item_list.extend(self._astropy_defined_solid_angle_units())
            item_list.extend(self._astropy_derived_solid_angle_units())

        unit_list = []
        for item in item_list:
            if isinstance(item, str):
                unit_list.append(item)
            elif isinstance(item, u.UnitBase):
                unit_list.append(item.to_string())
        unit_list = list(set(unit_list))
        return sorted(unit_list)

    def add_pixel_unit(self, item):
        if isinstance(item, str) \
                or isinstance(item, u.UnitBase):
            if item not in self.runtime_pixel_units:
                self.runtime_pixel_units.append(item)

    def add_solid_angle_unit(self, item):
        if isinstance(item, str) \
                or isinstance(item, u.UnitBase):
            if item not in self.runtime_solid_angle_units:
                self.runtime_solid_angle_units.append(item)


FLUX_UNIT_REGISTRY = FluxUnitRegistry()
AREA_UNIT_REGISTRY = AreaUnitRegistry()


class CubeVizUnit:
    def __init__(self, unit=None, unit_string=""):
        self._original_unit = unit
        self._unit = unit
        self._unit_string = unit_string
        self._type = "CubeVizUnit"
        self.is_convertable = False

    @property
    def unit(self):
        return self._unit

    @property
    def unit_string(self):
        return self._unit_string

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, type):
        if isinstance(type, str):
            self._type = type

    def populate_unit_layout(self, unit_layout):

        if self.unit_string:
            default_message = "CubeViz can not convert this unit: {0}."
            default_message = default_message.format(self.unit_string)
        else:
            default_message = "Unit not found."

        default_label = QLabel(default_message)
        unit_layout.addWidget(default_label)
        return unit_layout


class SpectralFluxDensity(CubeVizUnit):
    def __init__(self, unit, unit_string,
                 numeric=None,
                 spectral_flux_density=None,
                 area=None,
                 is_formatted=False):
        super(SpectralFluxDensity, self).__init__(unit, unit_string)

        self._type = "FormattedSpectralFluxDensity" if is_formatted else "SpectralFluxDensity"
        self.is_convertable = True

        self.numeric = numeric
        self.spectral_flux_density = spectral_flux_density
        self.area = area

        FLUX_UNIT_REGISTRY.add_unit(spectral_flux_density)

    def populate_unit_layout(self, unit_layout):
        if self.numeric is not None:
            numeric_string = str(self.numeric)
        elif self.unit is not None:
            numeric_string = self.unit.scale
        else:
            numeric_string = "1.0"
        numeric_input = QLineEdit(numeric_string)
        numeric_input.setFixedWidth(50)
        unit_layout.addWidget(numeric_input)
        multiplication = QLabel(" X ")
        unit_layout.addWidget(multiplication)

        flux_unit_str = self.spectral_flux_density.to_string()
        flux_options = FLUX_UNIT_REGISTRY.get_unit_list()
        if flux_unit_str not in flux_options:
            flux_options.append(flux_unit_str)
        index = flux_options.index(flux_unit_str)
        flux_combo = QComboBox()
        #flux_combo.setFixedWidth(200)
        flux_combo.addItems(flux_options)
        flux_combo.setCurrentIndex(index)
        unit_layout.addWidget(flux_combo)

        if self.area is not None:
            division = QLabel(" / ")
            unit_layout.addWidget(division)
            area = AREA_UNIT_REGISTRY.get_unit_list()
            area_combo = QComboBox()
            #area_combo.setFixedWidth(200)
            area_combo.width()
            area_combo.addItems(area)
            unit_layout.addWidget(area_combo)
        unit_layout.addStretch(1)
        return unit_layout


class UnknownUnit(CubeVizUnit):
    def __init__(self, unit, unit_string):
        super(UnknownUnit, self).__init__(unit, unit_string)
        self._type = "UnknownUnit"


class NoneUnit(CubeVizUnit):
    def __init__(self):
        super(NoneUnit, self).__init__(None, "")
        self._type = "NoneUnit"

    def populate_unit_layout(self, unit_layout):
        default_message = "No Units."
        default_label = QLabel(default_message)
        unit_layout.addWidget(default_label)
        return unit_layout


class ConvertFluxUnitGUI(QDialog):
    def __init__(self, controller, parent=None):
        super(ConvertFluxUnitGUI, self).__init__(parent=parent)
        self.setWindowFlags(self.windowFlags() | Qt.Tool)
        self.title = "Smoothing Selection"

        self.controller = controller
        self.data = controller.data
        self.controller_components = controller.components

        self._init_ui()

    def _init_ui(self):
        # LINE 1: Data component drop down
        self.component_prompt = QLabel("Data Component:")
        self.component_prompt.setWordWrap(True)
        # Add the data component labels to the drop down, with the ComponentID
        # set as the userData:
        if self.parent is not None and hasattr(self.parent, 'data_components'):
            self.label_data = [(str(cid), str(cid)) for cid in self.parent.data_components]
        else:
            self.label_data = [(str(cid), str(cid)) for cid in self.data.visible_components]

        default_index = 0
        self.component_combo = QComboBox()
        self.component_combo.setFixedWidth(200)
        update_combobox(self.component_combo, self.label_data, default_index=default_index)
        self.component_combo.currentIndexChanged.connect(self.update_unit_layout)

        # hbl is short for Horizontal Box Layout
        hbl1 = QHBoxLayout()
        hbl1.addWidget(self.component_prompt)
        hbl1.addWidget(self.component_combo)
        hbl1.addStretch(1)

        # LINE 2: Unit conversion layout
        self.unit_layout = QHBoxLayout()  # this is hbl2

        # Line 3: Buttons
        self.okButton = QPushButton("Convert Units")
        self.okButton.clicked.connect(self.call_main)
        self.okButton.setDefault(True)

        self.cancelButton = QPushButton("Cancel")
        self.cancelButton.clicked.connect(self.cancel)

        hbl3 = QHBoxLayout()
        hbl3.addStretch(1)
        hbl3.addWidget(self.cancelButton)
        hbl3.addWidget(self.okButton)

        vbl = QVBoxLayout()
        vbl.addLayout(hbl1)
        vbl.addLayout(self.unit_layout)
        vbl.addLayout(hbl3)
        self.setLayout(vbl)
        self.vbl = vbl

        self.update_unit_layout(default_index)

        self.show()

    def update_unit_layout(self, index):
        component_id = str(self.component_combo.currentData())

        widgets = (self.unit_layout.itemAt(i) for i in range(self.unit_layout.count()))
        for w in widgets:
            if isinstance(w, QSpacerItem):
                self.unit_layout.removeItem(w)
                continue
            elif isinstance(w, QWidgetItem):
                w = w.widget()

            if hasattr(w, "deleteLater"):
                w.deleteLater()

        if component_id in self.controller_components:
            cubeviz_unit = self.controller_components[component_id]
            cubeviz_unit.populate_unit_layout(self.unit_layout)
            if cubeviz_unit.is_convertable:
                self.okButton.setEnabled(True)
            else:
                self.okButton.setEnabled(False)
        else:
            default_message = "CubeViz can not convert this unit."
            default_label = QLabel(default_message)
            self.unit_layout.addWidget(default_label)
            self.okButton.setEnabled(False)

        self.unit_layout.update()
        self.vbl.update()

    def call_main(self):
        pass

    def cancel(self):
        self.close()


class FluxUnitController:
    def __init__(self, cubeviz_layout=None):
        self.cubeviz_layout = cubeviz_layout

        with open(DEFAULT_FLUX_UNITS_CONFIGS, 'r') as yamlfile:
            cfg = yaml.load(yamlfile)

        for new_unit_key in cfg["new_units"]:
            new_unit = cfg["new_units"][new_unit_key]
            try:
                u.Unit(new_unit["name"])
            except ValueError:
                if "base" in new_unit:
                    new_astropy_unit = u.def_unit(new_unit["name"], u.Unit(new_unit["base"]))
                else:
                    new_astropy_unit = u.def_unit(new_unit["name"])
            self.register_new_unit(new_astropy_unit)

        self.registered_units = cfg["registered_units"]

        self.data = None
        self.components = {}
        #TODO: Make this^ private

    @staticmethod
    def register_new_unit(new_unit):
        u.add_enabled_units(new_unit)
        if 'spectral flux density' in new_unit.physical_type:
            FLUX_UNIT_REGISTRY.add_unit(new_unit)
        if new_unit.decompose() == u.pix.decompose():
            AREA_UNIT_REGISTRY.add_pixel_unit(new_unit)
        if 'solid angle' in new_unit.physical_type:
            AREA_UNIT_REGISTRY.add_solid_angle_unit(new_unit)

    @staticmethod
    def string_to_unit(unit_string):
        try:
            if unit_string:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', AstropyWarning)
                    astropy_unit = u.Unit(unit_string)
                return astropy_unit
        except ValueError:
            print("Warning: Failed to convert {0} to an astropy unit.".format(unit_string))
        return None

    @staticmethod
    def unit_to_string(unit):
        if unit is None:
            return ""
        elif isinstance(unit, str):
            return unit
        elif isinstance(unit, u.Unit):
            return unit.to_string()
        elif isinstance(unit, u.quantity.Quantity):
            return unit.unit.to_string()
        else:
            raise ValueError("Invalid input unit type {0}.".format(type(unit)))

    def add_component_unit(self, component_id, unit=None):
        component_id = str(component_id)
        unit_string = self.unit_to_string(unit)

        if not unit_string:
            cubeviz_unit = NoneUnit()
        elif unit_string in self.registered_units:
            # TODO: match registered_unit types rather than strings (Hard)
            registered_unit = self.registered_units[unit_string]
            if "astropy_unit_string" in registered_unit:
                unit_string = registered_unit["astropy_unit_string"]
            astropy_unit = self.string_to_unit(unit_string)
            if registered_unit["numeric"]:
                numeric = float(registered_unit["numeric"])
            else:
                numeric = astropy_unit.scale
            spectral_flux_density = self.string_to_unit(registered_unit["spectral_flux_density"])
            area = self.string_to_unit(registered_unit["area"])
            cubeviz_unit = SpectralFluxDensity(astropy_unit, unit_string,
                                               numeric, spectral_flux_density, area,
                                               is_formatted=True)
        else:
            astropy_unit = self.string_to_unit(unit_string)
            if astropy_unit is not None and 'spectral flux density' in astropy_unit.physical_type:
                spectral_flux_density = self.string_to_unit(astropy_unit.to_string("unscaled"))
                numeric = astropy_unit.scale
                cubeviz_unit = SpectralFluxDensity(astropy_unit, unit_string,
                                                   numeric, spectral_flux_density,
                                                   area=None)
            else:
                cubeviz_unit = UnknownUnit(astropy_unit, unit_string)
        self.components[component_id] = cubeviz_unit
        return cubeviz_unit

    def remove_component_unit(self, component_id):
        component_id = str(component_id)
        if component_id in self.components:
            del self.components[component_id]

    def get_component_unit(self, component_id):
        component_id = str(component_id)
        if component_id in self.components:
            return self.components[component_id].unit
        return None

    def set_data(self, data):
        self.data = data
        self.components = {}
        for comp in data.visible_components:
            self.add_component_unit(comp, data.get_component(comp).units)

    def converter(self, parent=None):
        ex = ConvertFluxUnitGUI(self, parent)
