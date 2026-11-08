import simworld as S


class SpiDev:
    max_speed_hz = 0
    mode = 0

    def open(self, bus, dev):
        S.W.ev('spi_open', bus=bus, dev=dev)

    def writebytes(self, data):
        S.W.led_frame(list(data))

    def close(self):
        pass
