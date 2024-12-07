# -*- coding: utf-8 -*-
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2021-present Kaleidos INC

from collections import namedtuple

from django.db import connection
from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import EmptyResultSet
from taiga.base.api import serializers
from taiga.base.fields import Field, MethodField

Neighbor = namedtuple("Neighbor", "left right")


def get_neighbors(obj, results_set=None):
    """Get the neighbors of a model instance.

    The neighbors are the objects that are at the left/right of `obj` in the results set.

    :param obj: The object you want to know its neighbors.
    :param results_set: Find the neighbors applying the constraints of this set (a Django queryset
        object).

    :return: Tuple `<left neighbor>, <right neighbor>`. Left and right neighbors can be `None`.
    """
    if results_set is None:
        results_set = type(obj).objects.get_queryset()

    # Neighbors calculation is at least at project level
    results_set = results_set.filter(project_id=obj.project.id)

    compiler = results_set.query.get_compiler('default')
    try:
        base_sql, base_params = compiler.as_sql(with_col_aliases=True)
    except EmptyResultSet:
        # Generate a not empty queryset
        results_set = type(obj).objects.get_queryset().filter(project_id=obj.project.id)
        compiler = results_set.query.get_compiler('default')
        base_sql, base_params = compiler.as_sql(with_col_aliases=True)

    query = """
        WITH ID_AND_ROW AS (
            {base_sql}
        )
        SELECT *
        FROM (
            SELECT 
                "col1" AS id,
                ROW_NUMBER() OVER() AS row_num,
                LAG("col1", 1) OVER() AS prev,
                LEAD("col1", 1) OVER() AS next
            FROM ID_AND_ROW
        ) AS SELECTED_ID_AND_ROW
        WHERE id = %s;
    """

    query = query.format(base_sql=base_sql)  # Embed trusted base_sql into the query
    
    params = list(base_params) + [obj.id]
    
    # Use cursor as a context manager to ensure it is closed properly
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        row = cursor.fetchone()
        if row is None:
            return Neighbor(None, None)

    left_object_id = row[2]
    right_object_id = row[3]

    try:
        left = results_set.filter(id=left_object_id).first()
    except ObjectDoesNotExist:
        left = None

    try:
        right = results_set.filter(id=right_object_id).first()
    except ObjectDoesNotExist:
        right = None

    return Neighbor(left, right)


class NeighborSerializer(serializers.LightSerializer):
    id = Field()
    ref = Field()
    subject = Field()


class NeighborsSerializerMixin(serializers.LightSerializer):
    neighbors = MethodField()

    def serialize_neighbor(self, neighbor):
        if neighbor:
            return NeighborSerializer(neighbor).data
        return None

    def get_neighbors(self, obj):
        view, request = self.context.get("view", None), self.context.get("request", None)
        if view and request:
            queryset = view.filter_queryset(view.get_queryset())
            left, right = get_neighbors(obj, results_set=queryset)
        else:
            left = right = None

        return {
            "previous": self.serialize_neighbor(left),
            "next": self.serialize_neighbor(right)
        }
