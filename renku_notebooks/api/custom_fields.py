from typing import List, Mapping, Any
from marshmallow import fields
from marshmallow.exceptions import ValidationError
import re

from .. import config


class UnionField(fields.Field):
    """
    Field that deserializes multi-type input data to app-level objects.
    Adapted from https://stackoverflow.com/a/64034540
    """

    def __init__(self, val_types: List[fields.Field]):
        self.valid_types = val_types
        super().__init__()

    def _deserialize(
        self, value: Any, attr: str = None, data: Mapping[str, Any] = None, **kwargs
    ):
        """
        _deserialize defines a custom Marshmallow Schema Field that takes in mutli-type
        input data to app-level objects.

        Parameters
        ----------
        value : {Any}
            The value to be deserialized.

        Keyword Parameters
        ----------
        attr : {str} [Optional]
            The attribute/key in data to be deserialized. (default: {None})
        data : {Optional[Mapping[str, Any]]}
            The raw input data passed to the Schema.load. (default: {None})

        Raises
        ----------
        ValidationError : Exception
            Raised when the validation fails on a field or schema.
        """
        errors = []
        # iterate through the types being passed into UnionField via val_types
        for field in self.valid_types:
            try:
                # inherit deserialize method from Fields class
                return field.deserialize(value, attr, data, **kwargs)
            # if error, add error message to error list
            except ValidationError as error:
                errors.append(error.messages)

        raise ValidationError(errors)


def cpu_value_validation(x):
    return x > 0.0 and (x % 1 >= 0.001 or x % 1 == 0.0)


def memory_value_validation(x):
    return re.match(r"^(?:[1-9][0-9]*|[0-9]\.[0-9]*)[EPTGMK][i]{0,1}$", x) is not None


# used in the response from the server_options endpoint that is then
# used by the UI to present a set of options for the user to select when launching a session
serverOptionUICpuValue = fields.Number(validate=cpu_value_validation, required=True)
serverOptionUIDiskValue = fields.String(
    validate=memory_value_validation, required=True,
)
serverOptionUIMemoryValue = fields.String(
    validate=memory_value_validation, required=True,
)
serverOptionUIUrlValue = fields.Str(required=True,)

# used to validate the server options in the request to launch a notebook
serverOptionRequestCpuValue = fields.Number(
    validate=cpu_value_validation,
    required=False,
    missing=config.SERVER_OPTIONS_DEFAULTS["cpu_request"],
)
serverOptionRequestDiskValue = fields.String(
    validate=memory_value_validation,
    required=False,
    missing=config.SERVER_OPTIONS_DEFAULTS["disk_request"],
)
serverOptionRequestMemoryValue = fields.String(
    validate=memory_value_validation,
    required=False,
    missing=config.SERVER_OPTIONS_DEFAULTS["mem_request"],
)
serverOptionRequestUrlValue = fields.Str(
    required=False, missing=config.SERVER_OPTIONS_DEFAULTS["defaultUrl"]
)
