import helper


def dispatch(name):
    handlers = {"format": helper.format_result}
    handler = handlers[name]
    return handler(name)
