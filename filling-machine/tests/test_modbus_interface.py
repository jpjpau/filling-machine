import minimalmodbus
import pytest

from machine.modbus_interface import ModbusInterface

class FakeInstrument:
    """
    A fake MinimalModbus Instrument that stores registers and bits in a dict.
    """
    def __init__(self, port, slaveaddr):
        self._regs = {}
        class SerialStub: pass
        self.serial = SerialStub()

    def read_long(self, address, functioncode):
        return self._regs.get(address, 0)

    def write_register(self, address, value):
        self._regs[address] = value

    def write_bit(self, coil, on):
        self._regs[f"coil{coil}"] = on

@pytest.fixture(autouse=True)
def patch_minimalmodbus(monkeypatch):
    """
    Replace minimalmodbus.Instrument with FakeInstrument
    """
    monkeypatch.setattr(minimalmodbus, "Instrument",
                        lambda port, addr: FakeInstrument(port, addr))


def test_read_load_cell_signed_conversion():
    m = ModbusInterface()
    # Simulate -1 kg as 2^32 - 1000 grams
    fake_raw = (2**32 - 1000)
    m.scale._regs[0x0000] = fake_raw
    weight = m.read_load_cell()
    assert weight == pytest.approx(-1.0)


def test_vfd_register_writes():
    m = ModbusInterface()
    m.set_vfd_state(6)
    m.set_vfd_speed(128)
    assert m.vfd._regs[0x1E00] == 6
    assert m.vfd._regs[0x1E01] == 128


def test_set_valve_left_right_both():
    m = ModbusInterface()
    # Left open/close
    m.set_valve("left", "open")
    assert m.valves._regs["coil0"] == 1
    m.set_valve("left", "close")
    assert m.valves._regs["coil0"] == 0

    # Right open/close
    m.set_valve("right", "open")
    assert m.valves._regs["coil1"] == 1
    m.set_valve("right", "close")
    assert m.valves._regs["coil1"] == 0

    # Both open/close
    m.set_valve("both", "open")
    assert m.valves._regs["coil0"] == 1
    assert m.valves._regs["coil1"] == 1
    m.set_valve("both", "close")
    assert m.valves._regs["coil0"] == 0
    assert m.valves._regs["coil1"] == 0


def test_set_valve_invalid_valve():
    m = ModbusInterface()
    with pytest.raises(ValueError):
        m.set_valve("middle", "open")


def test_set_valve_invalid_action():
    m = ModbusInterface()
    with pytest.raises(ValueError):
        m.set_valve("left", "stop")
