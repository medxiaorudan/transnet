
from CIM14.ENTSOE.Equipment.Core import *
from CIM14.ENTSOE.Equipment.Wires import *
from CIM14.ENTSOE.Equipment.Generation.Production import *
from CIM14.ENTSOE.Equipment.LoadModel import LoadResponseCharacteristic

from PyCIM import cimwrite
from PyCIM.PrettyPrintXML import xmlpp

import uuid
from xml.dom.minidom import parse
from string import maketrans

class CimWriter:
    circuits = None
    id = 0
    winding_types = ['primary', 'secondary', 'tertiary']

    base_voltages_dict = dict()
    base_voltages_dict[110000] = BaseVoltage(nominalVoltage=110000)
    base_voltages_dict[220000] = BaseVoltage(nominalVoltage=220000)
    base_voltages_dict[380000] = BaseVoltage(nominalVoltage=380000)

    region = SubGeographicalRegion(Region=GeographicalRegion(name='Germany'))

    # osm id -> cim uuid
    uuid_by_osmid_dict = dict()
    # cim uuid -> cim object
    cimobject_by_uuid_dict = dict()
    # cim uuid -> cim connectivity node object
    connectivity_by_uuid_dict = dict()

    def __init__(self, circuits):
        self.circuits = circuits

    def publish(self, file_name):

        for circuit in self.circuits:
            station1 = circuit.members[0]
            station2 = circuit.members[len(circuit.members) - 1]
            line_length = self.line_length(circuit)

            if 'station' in station1.type:
                connectivity_node1 = self.substation_to_cim(station1, circuit.voltage)
            elif 'plant' in station1.type or 'generator' in station1.type:
                connectivity_node1 = self.generator_to_cim(station1)
            else:
                print 'Invalid circuit! - Skip circuit'
                circuit.print_circuit()
                continue

            if 'station' in station2.type:
                connectivity_node2 = self.substation_to_cim(station2, circuit.voltage)
            elif 'plant' in station2.type or 'generator' in station2.type:
                connectivity_node2 = self.generator_to_cim(station2)
            else:
                print 'Invalid circuit! - Skip circuit'
                circuit.print_circuit()
                continue

            self.line_to_cim(connectivity_node1, connectivity_node2, line_length, circuit.name, circuit.voltage)

        self.attach_loads()

        #d_vals=sorted(dictionary.values())
        #d_keys= sorted(dictionary, key=dictionary.get)
        #dictionary = collections.OrderedDict(zip(d_keys, d_vals))

        cimwrite(self.cimobject_by_uuid_dict, file_name + '.xml')
        cimwrite(self.cimobject_by_uuid_dict, file_name + '.rdf')

        #print '\nWhat is in path:\n'
        #print xmlpp(file_name + '.xml')

        # pretty write
        xml = parse(file_name + '.xml')
        pretty_xml_as_string = xml.toprettyxml()
        pretty_file = open(file_name + '_pretty.xml', "w")
        pretty_file.write(pretty_xml_as_string)
        pretty_file.close()

    def substation_to_cim(self, osm_substation, circuit_voltage):
        transformer_winding = None
        if self.uuid_by_osmid_dict.has_key(osm_substation.id):
            print 'Substation with OSMID ' + str(osm_substation.id) + ' already covered.'
            cim_substation = self.cimobject_by_uuid_dict[self.uuid_by_osmid_dict[osm_substation.id]]
            transformer = cim_substation.getEquipments()[0] # TODO check if there is actually one equipment
            for winding in transformer.getTransformerWindings():
                if int(circuit_voltage) == winding.ratedU:
                    print 'Transformer of Substation with OSMID ' + str(osm_substation.id) + ' already has winding for voltage ' + circuit_voltage
                    transformer_winding = winding
                    break
        else:
            print 'Create CIM Substation for OSMID ' + str(osm_substation.id)
            cim_substation = Substation(name='SS_' + str(osm_substation.id), Region=self.region)
            transformer = PowerTransformer(name='T_' + str(osm_substation.id) + '_' + str(osm_substation.voltage), EquipmentContainer=cim_substation)
            cim_substation.UUID = str(self.uuid())
            transformer.UUID = str(self.uuid())
            self.cimobject_by_uuid_dict[cim_substation.UUID] = cim_substation
            self.cimobject_by_uuid_dict[transformer.UUID] = transformer
            self.uuid_by_osmid_dict[osm_substation.id] = cim_substation.UUID
        if transformer_winding is None:
            transformer_winding = self.add_transformer_winding(osm_substation.id, osm_substation.voltage, circuit_voltage, transformer)
        return self.connectivity_by_uuid_dict[transformer_winding.UUID]

    def generator_to_cim(self, generator):
        if self.uuid_by_osmid_dict.has_key(generator.id):
            print 'Generator with OSMID ' + str(generator.id) + ' already covered.'
            generating_unit = self.cimobject_by_uuid_dict[self.uuid_by_osmid_dict[generator.id]]
        else:
            print 'Create CIM Generator for OSMID ' + str(generator.id)
            generating_unit = GeneratingUnit(name='G_' + str(generator.id), maxOperatingP=generator.nominal_power, minOperatingP=0,
                                             nominalP=generator.nominal_power)
            synchronous_machine = SynchronousMachine(name=CimWriter.escape_string(generator.name), operatingMode='generator', qPercent=0, x=0.01,
                                                     r=0.01, ratedS=generator.nominal_power, type='generator',
                                                     GeneratingUnit=generating_unit)
            generating_unit.UUID = str(self.uuid())
            synchronous_machine.UUID = str(self.uuid())
            self.cimobject_by_uuid_dict[generating_unit.UUID] = generating_unit
            self.cimobject_by_uuid_dict[synchronous_machine.UUID] = synchronous_machine
            self.uuid_by_osmid_dict[generator.id] = generating_unit.UUID
            connectivity_node = ConnectivityNode(name='CN' + str(generator.id))
            connectivity_node.UUID = str(self.uuid())
            self.cimobject_by_uuid_dict[connectivity_node.UUID] = connectivity_node
            terminal = Terminal(ConnectivityNode=connectivity_node, ConductingEquipment=synchronous_machine,
                                sequenceNumber=1)
            terminal.UUID = str(self.uuid())
            self.cimobject_by_uuid_dict[terminal.UUID] = terminal
            self.connectivity_by_uuid_dict[generating_unit.UUID] = connectivity_node
        return self.connectivity_by_uuid_dict[generating_unit.UUID]

    def line_to_cim(self, connectivity_node1, connectivity_node2, length, name, circuit_voltage):
        line = ACLineSegment(name=CimWriter.escape_string(name) + '_' + connectivity_node1.name + '_' + connectivity_node2.name, bch=0, r=0.3257, x=0.3153, r0=0.5336,
                             x0=0.88025, length=length, BaseVoltage=self.base_voltages_dict[int(circuit_voltage)])
        line.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[line.UUID] = line
        terminal1 = Terminal(ConnectivityNode=connectivity_node1, ConductingEquipment=line, sequenceNumber=1)
        terminal1.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[terminal1.UUID] = terminal1
        terminal2 = Terminal(ConnectivityNode=connectivity_node2, ConductingEquipment=line, sequenceNumber=2)
        terminal2.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[terminal2.UUID] = terminal2

    def get_winding_type(self, substation_voltage, circuit_voltage):
        i = 0
        for station_voltage in substation_voltage.split(';'):
            if station_voltage == circuit_voltage:
                return self.winding_types[i]
            i += 1
        return None

    def line_length(self, circuit):
        line_length = 0
        for line_part in circuit.members[1:(len(circuit.members) - 1)]:
            line_length += line_part.length()
        return line_length
    
    def uuid(self):
        self.id += 1
        return str(self.id)
        # return uuid.uuid1()

    def add_transformer_winding(self, osm_substation_id, osm_substation_voltage, winding_voltage, transformer):
        transformer_winding = TransformerWinding(b=0, x=1.0, r=1.0, connectionType='Yn',
                                                 windingType=self.get_winding_type(osm_substation_voltage, winding_voltage),
                                                 ratedU=int(winding_voltage), ratedS=5000000,
                                                 PowerTransformer=transformer,
                                                 BaseVoltage=self.base_voltages_dict[int(winding_voltage)])
        transformer_winding.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[transformer_winding.UUID] = transformer_winding
        connectivity_node = ConnectivityNode(name='CN_' + str(osm_substation_id) + '_' + winding_voltage)
        connectivity_node.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[connectivity_node.UUID] = connectivity_node
        terminal = Terminal(ConnectivityNode=connectivity_node, ConductingEquipment=transformer_winding,
                        sequenceNumber=1)
        terminal.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[terminal.UUID] = terminal
        self.connectivity_by_uuid_dict[transformer_winding.UUID] = connectivity_node
        return transformer_winding

    def attach_loads(self):
        for object in self.cimobject_by_uuid_dict.values():
            if isinstance(object, PowerTransformer):
                transformer = object
                osm_substation_id = transformer.name.split('_')[1]
                transformer_voltage = transformer.name.split('_')[2]
                transformer_voltage_levels = transformer_voltage.split(';')
                transformer_lower_voltage = transformer_voltage_levels[len(transformer_voltage_levels) - 1]
                self.attach_load(osm_substation_id, transformer_voltage, transformer_lower_voltage, transformer)

    def attach_load(self, osm_substation_id, transformer_voltage, winding_voltage, transformer):
        transformer_winding = None
        winding_voltages = []
        for winding in transformer.getTransformerWindings():
            winding_voltages.append(str(winding.ratedU))
            if int(winding_voltage) == winding.ratedU:
                transformer_winding = winding
        # add winding for lower voltage, if not already existing or
        # add winding if substaion is a switching station (only one voltage level)
        if transformer_winding is None or len(transformer_voltage.split(';')) == 1:
            transformer_winding = self.add_transformer_winding(osm_substation_id, transformer_voltage, winding_voltage, transformer)
        connectivity_node = self.connectivity_by_uuid_dict[transformer_winding.UUID]
        load_response_characteristic = LoadResponseCharacteristic(exponentModel=False, pConstantPower=100000)
        load_response_characteristic.UUID = str(self.uuid())
        energy_consumer = EnergyConsumer(name='L_' + str(osm_substation_id), LoadResponse=load_response_characteristic)
        energy_consumer.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[load_response_characteristic.UUID] = load_response_characteristic
        self.cimobject_by_uuid_dict[energy_consumer.UUID] = energy_consumer
        terminal = Terminal(ConnectivityNode=connectivity_node, ConductingEquipment=energy_consumer,
                        sequenceNumber=1)
        terminal.UUID = str(self.uuid())
        self.cimobject_by_uuid_dict[terminal.UUID] = terminal

    @staticmethod
    def escape_string(string):
        if string is not None:
            return string.translate(maketrans('-]^$/. ', '_______'))
        return ''