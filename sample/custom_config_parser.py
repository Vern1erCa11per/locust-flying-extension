

def parse(locust_config, user_config):

    # generate user params (should be list)
    user_params = list(range(locust_config["clients"]))

    # generate common param
    common_param = {}
    common_param["max_wait"] = user_config["max_wait"]

    return user_params, common_param