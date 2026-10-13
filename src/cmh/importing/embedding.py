"""Bound long legacy records without discarding text or changing the native write limit."""
import codecs
import math

from cmh.services.embedding import validate_vector


class ImportEmbeddingProvider:
    def __init__(self, provider):
        self.provider = provider
        self.model = provider.model
        self.dimensions = provider.dimensions
        self.calls = 0
        self.chunked_records = 0

    def embed(self, content):
        data = content.encode("utf-8")
        decoder = codecs.getincrementaldecoder("utf-8")()
        pieces = [decoder.decode(data[start:start + 8000]) for start in range(0, len(data), 8000)]
        final = decoder.decode(b"", final=True)
        if final:
            pieces.append(final)
        pieces = [piece for piece in pieces if piece]
        if len(pieces) > 1:
            self.chunked_records += 1
        vectors = []
        for piece in pieces:
            self.calls += 1
            vectors.append((len(piece.encode("utf-8")), self.provider.embed(piece)))
        if len(vectors) == 1:
            return vectors[0][1]
        combined = [sum(weight * vector[index] for weight, vector in vectors)
                    for index in range(self.dimensions)]
        norm = math.sqrt(sum(value * value for value in combined))
        return validate_vector([value / norm for value in combined] if norm else combined, self.dimensions)
