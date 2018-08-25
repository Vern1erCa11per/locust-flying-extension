import logging
import random
from greenlet import GreenletExit

import gevent
import six
from locust import HttpLocust, runners, events
from locust.runners import LocalLocustRunner

logger = logging.getLogger(__name__)

class IdentifiedHttpLocust(HttpLocust):

    def __init__(self, user_info, target_info):
        super().__init__()
        self.user_info = user_info
        self.target_info = target_info

class ParameterizableLocustRunner(LocalLocustRunner):

    def __init__(self, locust_classes, options, user_infos, target_info):
        super().__init__(locust_classes, options)
        self.user_infos = user_infos
        self.target_info = target_info

    def spawn_locusts(self, spawn_count=None, stop_timeout=None, wait=False):
        if spawn_count is None:
            spawn_count = self.num_clients

        if self.num_requests is not None:
            self.stats.max_requests = self.num_requests

        bucket = self.weight_locusts(spawn_count, stop_timeout)
        spawn_count = len(bucket)

        if spawn_count > len(self.user_infos):
            raise Exception("lacks enough user information")

        if self.state == runners.STATE_INIT or self.state == runners.STATE_STOPPED:
            self.state = runners.STATE_HATCHING
            self.num_clients = spawn_count
        else:
            self.num_clients += spawn_count

        runners.logger.info("Hatching and swarming %i clients at the rate %g clients/s..." % (spawn_count, self.hatch_rate))
        occurence_count = dict([(l.__name__, 0) for l in self.locust_classes])

        def hatch():
            sleep_time = 1.0 / self.hatch_rate
            while True:
                if not bucket:
                    logger.info("All locusts hatched: %s" % ", ".join(
                        ["%s: %d" % (name, count) for name, count in six.iteritems(occurence_count)]))
                    events.hatch_complete.fire(user_count=self.num_clients)
                    return

                locust = bucket.pop(random.randint(0, len(bucket) - 1))
                user_info = self.user_infos.pop(random.randint(0, len(self.user_infos) - 1))
                occurence_count[locust.__name__] += 1

                def start_locust(_):
                    try:
                        if issubclass(locust , IdentifiedHttpLocust):
                            locust(user_info, self.target_info).run()
                        else:
                            locust().run()
                    except GreenletExit:
                        pass

                new_locust = self.locusts.spawn(start_locust, locust)
                if len(self.locusts) % 10 == 0:
                    logger.debug("%i locusts hatched" % len(self.locusts))
                gevent.sleep(sleep_time)

        hatch()
        if wait:
            self.locusts.join()
            logger.info("All locusts dead\n")




