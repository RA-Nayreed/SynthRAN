"""Render run-scoped Contiki-NG/Cooja inputs for SynthRAN experiments."""

from __future__ import annotations

import json
from pathlib import Path
from xml.sax.saxutils import escape

from synthran.experiment import ExperimentError, ExperimentScenario


MOTE_INTERFACES = (
    "org.contikios.cooja.interfaces.Position",
    "org.contikios.cooja.interfaces.Battery",
    "org.contikios.cooja.contikimote.interfaces.ContikiVib",
    "org.contikios.cooja.contikimote.interfaces.ContikiMoteID",
    "org.contikios.cooja.contikimote.interfaces.ContikiRS232",
    "org.contikios.cooja.contikimote.interfaces.ContikiBeeper",
    "org.contikios.cooja.interfaces.RimeAddress",
    "org.contikios.cooja.interfaces.IPAddress",
    "org.contikios.cooja.contikimote.interfaces.ContikiRadio",
    "org.contikios.cooja.contikimote.interfaces.ContikiButton",
    "org.contikios.cooja.contikimote.interfaces.ContikiPIR",
    "org.contikios.cooja.contikimote.interfaces.ContikiClock",
    "org.contikios.cooja.contikimote.interfaces.ContikiLED",
    "org.contikios.cooja.contikimote.interfaces.ContikiCFS",
    "org.contikios.cooja.contikimote.interfaces.ContikiEEPROM",
    "org.contikios.cooja.interfaces.Mote2MoteRelations",
    "org.contikios.cooja.interfaces.MoteAttributes",
)


def render_generated_header(scenario: ExperimentScenario) -> str:
    return "\n".join(
        (
            "#ifndef SYNTHRAN_EXPERIMENT_GENERATED_H_",
            "#define SYNTHRAN_EXPERIMENT_GENERATED_H_",
            "",
            f'#define SYNTHRAN_RUN_ID "{scenario.run_id}"',
            f'#define SYNTHRAN_TOPIC_PREFIX "{scenario.topic_prefix}"',
            '#define SYNTHRAN_EDGE_BROKER_IPV6 "fd00::1"',
            f"#define SYNTHRAN_SENSOR_PERIOD_SECONDS {scenario.sensor_period_seconds}",
            "",
            "#endif",
            "",
        )
    )


def _interfaces() -> str:
    return "\n".join(
        f"      <moteinterface>{escape(interface)}</moteinterface>"
        for interface in MOTE_INTERFACES
    )


def _mote(mote_id: int, x: float, y: float) -> str:
    return f"""      <mote>
        <interface_config>
          org.contikios.cooja.interfaces.Position
          <pos x=\"{x:.1f}\" y=\"{y:.1f}\" />
        </interface_config>
        <interface_config>
          org.contikios.cooja.contikimote.interfaces.ContikiMoteID
          <id>{mote_id}</id>
        </interface_config>
      </mote>"""


def render_cooja_scenario(scenario: ExperimentScenario) -> str:
    """Render one border router plus exactly ten deterministic MQTT sensors."""

    if scenario.sensor_count != 10:
        raise ExperimentError("Cooja renderer supports exactly 10 sensors")

    positions = (
        (-30.0, -20.0),
        (-10.0, -20.0),
        (10.0, -20.0),
        (30.0, -20.0),
        (-40.0, 10.0),
        (-20.0, 10.0),
        (0.0, 10.0),
        (20.0, 10.0),
        (40.0, 10.0),
        (0.0, 40.0),
    )
    sensor_motes = "\n".join(
        _mote(index, x, y)
        for index, (x, y) in enumerate(positions, start=1)
    )

    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<simconf version=\"2022112801\">
  <simulation>
    <title>SynthRAN {escape(scenario.run_id)}</title>
    <speedlimit>1.0</speedlimit>
    <randomseed>{scenario.cooja_seed}</randomseed>
    <motedelay_us>1000000</motedelay_us>
    <radiomedium>
      org.contikios.cooja.radiomediums.UDGM
      <transmitting_range>75.0</transmitting_range>
      <interference_range>100.0</interference_range>
      <success_ratio_tx>1.0</success_ratio_tx>
      <success_ratio_rx>1.0</success_ratio_rx>
    </radiomedium>
    <events>
      <logoutput>40000</logoutput>
    </events>
    <motetype>
      org.contikios.cooja.contikimote.ContikiMoteType
      <identifier>synthran-br</identifier>
      <description>SynthRAN RPL border router</description>
      <source>[CONTIKI_DIR]/examples/rpl-border-router/border-router.c</source>
      <commands>$(MAKE) TARGET=cooja clean
$(MAKE) -j$(CPUS) border-router.cooja TARGET=cooja</commands>
{_interfaces()}
{_mote(250, 0.0, 0.0)}
    </motetype>
    <motetype>
      org.contikios.cooja.contikimote.ContikiMoteType
      <identifier>synthran-sensor</identifier>
      <description>SynthRAN deterministic MQTT sensor</description>
      <source>[CONFIG_DIR]/../sensor/synthran-sensor.c</source>
      <commands>$(MAKE) TARGET=cooja CONTIKI=[CONTIKI_DIR] clean
$(MAKE) -j$(CPUS) TARGET=cooja CONTIKI=[CONTIKI_DIR] synthran-sensor.cooja</commands>
{_interfaces()}
{sensor_motes}
    </motetype>
  </simulation>
  <plugin>
    org.contikios.cooja.serialsocket.SerialSocketServer
    <mote_arg>0</mote_arg>
    <plugin_config>
      <port>{scenario.serial_socket_port}</port>
      <bound>true</bound>
    </plugin_config>
    <bounds x=\"10\" y=\"10\" height=\"120\" width=\"380\" z=\"1\" />
  </plugin>
  <plugin>
    org.contikios.cooja.plugins.ScriptRunner
    <plugin_config>
      <script>TIMEOUT(86400000); /* one day safety timeout */
sim.setSpeedLimit(1.0);
while (true) {{ YIELD(); }}</script>
      <active>true</active>
    </plugin_config>
    <bounds x=\"400\" y=\"10\" height=\"500\" width=\"600\" />
  </plugin>
</simconf>
"""


def write_run_inputs(
    scenario: ExperimentScenario,
    *,
    run_directory: Path,
) -> tuple[Path, Path, Path]:
    """Materialize run-scoped generated inputs below the ignored run directory."""

    sensor_dir = run_directory / "sensor"
    cooja_dir = run_directory / "cooja"
    sensor_dir.mkdir(parents=True, exist_ok=True)
    cooja_dir.mkdir(parents=True, exist_ok=True)

    header = sensor_dir / "experiment-generated.h"
    csc = cooja_dir / "experiment.csc"
    scenario_json = run_directory / "scenario.json"

    header.write_text(render_generated_header(scenario), encoding="utf-8", newline="\n")
    csc.write_text(render_cooja_scenario(scenario), encoding="utf-8", newline="\n")
    scenario_json.write_text(
        json.dumps(scenario.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return header, csc, scenario_json
