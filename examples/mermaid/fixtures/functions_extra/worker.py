import helper


class Worker:
    def run(self):
        return self.process()

    def process(self):
        return helper.format_result(self._value())

    def _value(self):
        return 42
