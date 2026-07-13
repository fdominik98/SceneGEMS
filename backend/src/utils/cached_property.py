class CachedProperty:
    def __init__(self, func):
        self.func = func
        self.cache_name = f"_{func.__name__}_cache"
        self.version_name = f"_{func.__name__}_version"

    def __get__(self, instance, owner):
        if instance is None:
            return self
        attr_version = instance.__dict__.get(self.version_name, -1)
        current_version = hash(tuple(instance.__dict__.items()))  # Detect changes
        if attr_version != current_version:
            instance.__dict__[self.cache_name] = self.func(instance)
            instance.__dict__[self.version_name] = current_version
        return instance.__dict__[self.cache_name]
