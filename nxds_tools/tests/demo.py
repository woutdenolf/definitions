"""The demo classes of the proposal, written to a directory by the tests.

They are written at test time rather than kept as files, so that tools that
scan the repository for ``*.nxdl.xml`` do not pick them up.
"""

from pathlib import Path

_NS = (
    'xmlns="http://definition.nexusformat.org/nxdl/3.1" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
)

DEMO_NXDL = f"""<?xml version="1.0" encoding="UTF-8"?>
<definition name="NXdemo_x" extends="NXobject" type="group" category="application" {_NS}>
  <symbols><symbol name="nE"><doc>number of energies</doc></symbol></symbols>
  <doc>Demo: absorption against energy.</doc>
  <group type="NXentry">
    <field name="definition"><enumeration><item value="NXdemo_x"/></enumeration></field>
    <field name="title" recommended="true"/>
    <group type="NXinstrument">
      <group name="monochromator" type="NXmonochromator">
        <field name="energy" type="NX_FLOAT" units="NX_ENERGY">
          <dimensions rank="1"><dim index="1" value="nE"/></dimensions>
        </field>
      </group>
      <group name="counter" type="NXdemo_counter_x">
        <field name="mode"/>
        <field name="i0_counts">
          <dimensions rank="1"><dim index="1" value="nE"/></dimensions>
        </field>
      </group>
    </group>
    <group type="NXdata">
      <attribute name="signal"><enumeration><item value="mu"/></enumeration></attribute>
      <field name="mu" type="NX_FLOAT">
        <dimensions rank="1"><dim index="1" value="nE"/></dimensions>
      </field>
      <link name="energy" target="/NXentry/NXinstrument/monochromator:NXmonochromator/energy"/>
    </group>
  </group>
</definition>
"""

COUNTER_NXDL = f"""<?xml version="1.0" encoding="UTF-8"?>
<definition name="NXdemo_counter_x" extends="NXobject" type="group" category="base" {_NS}>
  <doc>Demo: a counter with several channels.</doc>
  <field name="mode">
    <doc>Counting mode.</doc>
    <enumeration><item value="timer"/><item value="monitor"/></enumeration>
  </field>
  <field name="CHANNEL_counts" nameType="partial" type="NX_INT" units="NX_COUNT">
    <doc>Counts of one channel.</doc>
  </field>
  <group type="NXsensor"><doc>Any sensor.</doc></group>
</definition>
"""

DEMO_NXDS = """nxds: "0.1"
class: NXdemo_y
category: application
describes: NXroot
doc: "Demo: absorption against energy."
defaults: {min: 1, binding: true}
symbols:
  nE: {doc: number of energies}
children:
  ENTRY:
    node: group
    class: NXentry
    name: {any: true}
    children:
      definition: {node: dataset, enum: [NXdemo_y]}
      title: {node: dataset, occurs: {min: 0}, recommended: true}
      INSTRUMENT:
        node: group
        class: NXinstrument
        name: {any: true}
        children:
          monochromator:
            node: group
            class: NXmonochromator
            refines: MONOCHROMATOR
            children:
              energy: {node: dataset, type: NX_FLOAT, units: {category: NX_ENERGY}, shape: [nE]}
          counter:
            node: group
            class: NXdemo_counter_y
            children:
              mode: {node: dataset}
              i0_counts: {node: dataset, refines: CHANNEL_counts, shape: [nE]}
      DATA:
        node: group
        class: NXdata
        name: {any: true}
        attributes:
          signal: {enum: [mu]}
        children:
          mu: {node: dataset, type: NX_FLOAT, shape: [nE]}
          energy: {node: link, target: ENTRY/INSTRUMENT/monochromator/energy}
"""

COUNTER_NXDS = """nxds: "0.1"
class: NXdemo_counter_y
category: base
extends: NXobject
doc: "Demo: a counter with several channels."
defaults: {min: 0, binding: false}
children:
  mode:
    node: dataset
    type: NX_CHAR
    enum: [timer, monitor]
    doc: Counting mode.
  CHANNEL_counts:
    node: dataset
    name: {template: "{CHANNEL}_counts"}
    type: NX_INT
    units: {category: NX_COUNT}
    doc: Counts of one channel.
  SENSOR: {node: group, class: NXsensor, name: {any: true}, doc: Any sensor.}
"""

DEMO_REQUIRE = """nxds: "0.1"
class: NXdemo_z
category: application
describes: NXroot
defaults: {min: 1, binding: true}
children:
  ENTRY:
    node: group
    class: NXentry
    name: {any: true}
    children:
      definition: {node: dataset, enum: [NXdemo_z]}
      DATA:
        node: group
        class: NXdata
        name: {any: true}
        children:
          mu: {node: dataset, type: NX_FLOAT, occurs: {min: 0}}
          fluo: {node: dataset, type: NX_FLOAT, occurs: {min: 0}}
        require:
          at_least_one_of: [mu, fluo]
"""


def write_demo(directory: Path) -> Path:
    """Write the demo classes; ``_x`` in NXDL, ``_y`` in NXDS, ``_z`` uses require."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "NXdemo_x.nxdl.xml").write_text(DEMO_NXDL)
    (directory / "NXdemo_counter_x.nxdl.xml").write_text(COUNTER_NXDL)
    (directory / "NXdemo_y.nxds.yaml").write_text(DEMO_NXDS)
    (directory / "NXdemo_counter_y.nxds.yaml").write_text(COUNTER_NXDS)
    (directory / "NXdemo_z.nxds.yaml").write_text(DEMO_REQUIRE)
    return directory
