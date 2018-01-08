'''
Plugin system inspired by:
https://eli.thegreenplace.net/2012/08/07/fundamental-concepts-of-plugin-infrastructures
'''


class PluginRegistry(type):
    plugins = []

    def __init__(cls, name, bases, attrs):
        super().__init__(name, bases, attrs)

        if name != 'BasePlugin':
            PluginRegistry.plugins.append(cls)
