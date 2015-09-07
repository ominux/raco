

class RepresentationProperties(object):
    def __init__(self, hash_partitioned=None, sorted=None, grouped=None):
        """
        @param hash_partitioned: None or set of AttributeRefs in hash key
        @param sorted: None or list of (AttributeRefs, ASC/DESC) in sort order
        @param grouped: None or list of AttributeRefs to group by

        None means that no knowledge about the interesting property is
        known
        """
        if hash_partitioned is None:
            self.hash_partitioned = set()
        else:
            self.hash_partitioned = hash_partitioned

        if sorted is not None or grouped is not None:
            raise NotImplementedError("sorted and grouped not yet supported")