.. _NXdemo_counter_phase1:

NXdemo_counter_phase1
=====================

**Category:** base · **Status:** local · **Extends:** :ref:`NXobject` · **Source:** ``phase1/NXdemo_counter_phase1.nxdl.xml``

Demo: a counter with several channels.

Members
-------

*required* means at least one object, *recommended* that its absence is reported, *optional* neither. Values marked *provisional* depend on an open decision of the NIAC.

- **@default**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXobject`; *provisional:* Q1

  .. index:: plotting

  Declares which child group contains a path leading
  to a :ref:`NXdata` group or a group using a base class
  extending :ref:`NXdata`.

  It is recommended (as of NIAC2014) to use this attribute
  to help define the path to the default dataset to be plotted.
  See https://www.nexusformat.org/2014_How_to_find_default_data.html
  for a summary of the discussion.

- **COLLECTION** (any name): group, :ref:`NXcollection`, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q11

- **DATA** (any name): group, :ref:`NXdata`, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q11

- **LOG** (any name): group, :ref:`NXlog`, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q11

- **NOTE** (any name): group, :ref:`NXnote`, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q11

- **PARAMETERS** (any name): group, :ref:`NXparameters`, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q11

- **{GROUPNAME}_log** (name template): group, :ref:`NXlog`, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q3

  NXlog group containing logged values of GROUPNAME.

- **{FIELDNAME}_set** (name template): dataset, ``NX_NUMBER``, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q3

  Target values of FIELDNAME. 

- **{FIELDNAME}_errors** (name template): dataset, ``NX_NUMBER``, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q3

  Uncertainties of FIELDNAME values.

- **{FIELDNAME}_weights** (name template): dataset, ``NX_NUMBER``, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q3

  Weights of FIELDNAME values.

- **{FIELDNAME}_mask** (name template): dataset, ``NX_BOOLEAN``, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q3

  Boolean mask of FIELDNAME values. The value is masked if set to 1.

- **identifier{NAME}** (name template): dataset, ``NX_CHAR``, *optional [0..∞]*

  inherited from :ref:`NXobject`; *provisional:* Q1, Q3

  An identifier for a (persistent) resource.

  An identifier, provided by some authority, that has been assigned to an
  object described by this ``NXobject``. To be useful, the identifier
  must not be reassigned to a different real-world object. It is typical for
  there to be some mechanism to resolve an identifier, obtaining metadata
  about the object. Identifiers for which some guarantees exist regarding
  this resolution process are called persistent identifiers.
  Persistent identifiers are also known as PIDs.

  - **@type**: attribute, ``NX_CHAR``, *optional*

    inherited from :ref:`NXobject`; *provisional:* Q1

    Suggested values: ``ARK``, ``DOI``, ``Hdl``, ``IGSN``, ``ISNI``, ``ISSN``, ``ISSN-L``, ``ORCID``, ``PURL``, ``ROR``, ``URL``, ``URN``

    The type of identifier used.

    It is recommended to use the most specific type when describing the identifier.

    For example, all IGSNs (see below) are DOIs and all DOIs are Handles; however, an IGSN should have type IGSN (and not DOI or Hdl).
    Similarly, an ARK, Purl, ORCID and ROR identifiers should have their corresponding types and should not use the more generic URL identifier.

- **mode**: dataset, ``NX_CHAR``, *optional*

  *provisional:* Q1

  Allowed values: ``timer``, ``monitor``

  Counting mode.

- **{CHANNEL}_counts** (name template): dataset, ``NX_INT``, units ``NX_COUNT``, *optional [0..∞]*

  *provisional:* Q1, Q3

  Counts of one channel, for example ``i0_counts``.

- **SENSOR** (any name): group, :ref:`NXsensor`, *optional [0..∞]*

  *provisional:* Q1, Q11

  Any sensor read out with the counter.

