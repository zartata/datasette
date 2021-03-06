.. _metadata:

Metadata
========

Data loves metadata. Any time you run Datasette you can optionally include a
JSON file with metadata about your databases and tables. Datasette will then
display that information in the web UI.

Run Datasette like this::

    datasette database1.db database2.db --metadata metadata.json

Your ``metadata.json`` file can look something like this::

    {
        "title": "Custom title for your index page",
        "description": "Some description text can go here",
        "license": "ODbL",
        "license_url": "https://opendatacommons.org/licenses/odbl/",
        "source": "Original Data Source",
        "source_url": "http://example.com/"
    }

The above metadata will be displayed on the index page of your Datasette-powered
site. The source and license information will also be included in the footer of
every page served by Datasette.

Any special HTML characters in ``description`` will be escaped. If you want to
include HTML in your description, you can use a ``description_html`` property
instead.

Per-database and per-table metadata
-----------------------------------

Metadata at the top level of the JSON will be shown on the index page and in the
footer on every page of the site. The license and source is expected to apply to
all of your data.

You can also provide metadata at the per-database or per-table level, like this::

    {
        "databases": {
            "database1": {
                "source": "Alternative source",
                "source_url": "http://example.com/",
                "tables": {
                    "example_table": {
                        "description_html": "Custom <em>table</em> description",
                        "license": "CC BY 3.0 US",
                        "license_url": "https://creativecommons.org/licenses/by/3.0/us/"
                    }
                }
            }
        }
    }

Each of the top-level metadata fields can be used at the database and table level.

.. _metadata_source_license_about:

Source, license and about
-------------------------

The three visible metadata fields you can apply to everything, specific databases or specific tables are source, license and about. All three are optional.

**source** and **source_url** should be used to indicate where the underlying data came from.

**license** and **license_url** should be used to indicate the license under which the data can be used.

**about** and **about_url** can be used to link to further information about the project - an accompanying blog entry for example.

For each of these you can provide just the ``*_url`` field and Datasette will treat that as the default link label text and display the URL directly on the page.

Specifying units for a column
-----------------------------

Datasette supports attaching units to a column, which will be used when displaying
values from that column. SI prefixes will be used where appropriate.

Column units are configured in the metadata like so::

    {
        "databases": {
            "database1": {
                "tables": {
                    "example_table": {
                        "units": {
                            "column1": "metres",
                            "column2": "Hz"
                        }
                    }
                }
            }
        }
    }

Units are interpreted using Pint_, and you can see the full list of available units in
Pint's `unit registry`_. You can also add `custom units`_ to the metadata, which will be
registered with Pint::

    {
        "custom_units": [
            "decibel = [] = dB"
        ]
    }

.. _Pint: https://pint.readthedocs.io/
.. _unit registry: https://github.com/hgrecco/pint/blob/master/pint/default_en.txt
.. _custom units: http://pint.readthedocs.io/en/latest/defining.html

.. _metadata_sortable_columns:

Setting which columns can be used for sorting
---------------------------------------------

Datasette allows any column to be used for sorting by default. If you need to
control which columns are available for sorting you can do so using the optional
``sortable_columns`` key::

    {
        "databases": {
            "database1": {
                "tables": {
                    "example_table": {
                        "sortable_columns": [
                            "height",
                            "weight"
                        ]
                    }
                }
            }
        }
    }

This will restrict sorting of ``example_table`` to just the ``height`` and
``weight`` columns.

You can also disable sorting entirely by setting ``"sortable_columns": []``

By default, database views in Datasette do not support sorting. You can use ``sortable_columns`` to enable specific sort orders for a view called ``name_of_view`` in the database ``my_database`` like so::

    {
        "databases": {
            "my_database": {
                "tables": {
                    "name_of_view": {
                        "sortable_columns": [
                            "clicks",
                            "impressions"
                        ]
                    }
                }
            }
        }
    }

.. _label_columns:

Specifying the label column for a table
---------------------------------------

Datasette's HTML interface attempts to display foreign key references as
labelled hyperlinks. By default, it looks for referenced tables that only have
two columns: a primary key column and one other. It assumes that the second
column should be used as the link label.

If your table has more than two columns you can specify which column should be
used for the link label with the ``label_column`` property::

    {
        "databases": {
            "database1": {
                "tables": {
                    "example_table": {
                        "label_column": "title"
                    }
                }
            }
        }
    }

Hiding tables
-------------

You can hide tables from the database listing view (in the same way that FTS and
Spatialite tables are automatically hidden) using ``"hidden": true``::

    {
        "databases": {
            "database1": {
                "tables": {
                    "example_table": {
                        "hidden": true
                    }
                }
            }
        }
    }
