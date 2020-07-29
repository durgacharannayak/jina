__copyright__ = "Copyright (c) 2020 Jina AI Limited. All rights reserved."
__license__ = "Apache-2.0"

from collections import defaultdict
from typing import Dict, List, Iterable

from . import BaseRecursiveDriver
from ..excepts import NoExplicitMessage
from ..proto import jina_pb2


class ReduceDriver(BaseRecursiveDriver):
    """:class:`ReduceDriver` merges envelope of all requests """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prev_requests = None
        self._prev_messages = None
        self._pending_msgs = defaultdict(list)  # type: Dict[str, List]

    @property
    def prev_reqs(self) -> List['jina_pb2.Request']:
        """Get all previous requests that has the same ``request_id``, shortcut to ``self.pea.prev_requests``

        This returns ``None`` when ``num_part=1``.
        """
        return self._prev_requests

    @property
    def prev_reqs_exclude_last(self) -> List['jina_pb2.Request']:
        """Get all previous requests but excluding the current request (last received request)
        """
        return self._prev_requests[:-1]

    @property
    def prev_msgs(self) -> List['jina_pb2.Message']:
        """Get all previous messages that has the same ``request_id``, shortcut to ``self.pea.prev_messages``

        This returns ``None`` when ``num_part=1``.
        """
        return self._prev_messages

    def __call__(self, *args, **kwargs):
        if self.envelope.num_part[-1] > 1:
            req_id = self.envelope.request_id
            self._pending_msgs[req_id].append(self.msg)
            num_req = len(self._pending_msgs[req_id])

            self.logger.info(f'collected {num_req}/{self.envelope.num_part[-1]} parts of {type(self.req).__name__}')

            if num_req == self.envelope.num_part[-1]:
                self._prev_messages = self._pending_msgs.pop(req_id)
                self._prev_requests = [getattr(v.request, v.request.WhichOneof('body')) for v in
                                       self._prev_messages]
            else:
                raise NoExplicitMessage

            self.reduce(*args, **kwargs)
            self.envelope.num_part.pop(-1)

    def reduce(self, *args, **kwargs):
        """ Reduce the message from all requests by merging their envelopes
        """
        # take unique routes by service identity
        routes = {(r.pod + r.pod_id): r for m in self.prev_msgs for r in m.envelope.routes}
        self.msg.envelope.ClearField('routes')
        self.msg.envelope.routes.extend(
            sorted(routes.values(), key=lambda x: (x.start_time.seconds, x.start_time.nanos)))


class ReduceAllDriver(ReduceDriver):
    """:class:`ReduceAllDriver` merges chunks and matches from all requests """

    def reduce(self, *args, **kwargs):
        # use docs in the last request to set the pointers
        self.doc_pointers = {d.id: d for d in self.req.docs}
        # traverse apply on ALL requests collected
        for r in self.prev_reqs_exclude_last:
            self._traverse_apply(r.docs, *args, **kwargs)
        super().reduce(*args, **kwargs)

    def _apply_all(self, docs: Iterable['jina_pb2.Document'], context_doc: 'jina_pb2.Document', field: str, *args,
                   **kwargs):
        if context_doc:
            if context_doc.id not in self.doc_pointers:
                self.doc_pointers[context_doc.id] = context_doc
            else:
                getattr(self.doc_pointers[context_doc.id], field).extend(docs)
