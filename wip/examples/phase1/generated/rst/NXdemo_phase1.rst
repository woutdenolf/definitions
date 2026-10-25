.. _NXdemo_phase1:

NXdemo_phase1
=============

**Category:** application · **Status:** local · **Describes:** :ref:`NXroot` · **Source:** ``phase1/NXdemo_phase1.nxdl.xml``

Demo: absorption against energy.

Symbols
-------

- ``nE``: number of energies

Members
-------

*required* means at least one object, *recommended* that its absence is reported, *optional* neither. Values marked *provisional* depend on an open decision of the NIAC.

- **@default**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXobject`; refined by :ref:`NXroot`; *provisional:* Q1

  .. index:: find the default plottable data
  .. index:: plotting
  .. index:: default attribute value

  Declares which :ref:`NXentry` group contains
  the data to be shown by default.
  It is used to resolve ambiguity when
  more than one :ref:`NXentry` group exists.
  The value :ref:`names <validItemName>` the default :ref:`NXentry` group.  The
  value must be the name of a child of the current group. The child must be a
  NeXus group or a link to a NeXus group.

  It is recommended (as of NIAC2014) to use this attribute
  to help define the path to the default dataset to be plotted.
  See https://www.nexusformat.org/2014_How_to_find_default_data.html
  for a summary of the discussion.

- **@file_time**: attribute, ``NX_DATE_TIME``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Date and time file was originally created

- **@file_name**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  File name of original NeXus file

- **@file_update_time**: attribute, ``NX_DATE_TIME``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Date and time of last file change at close

- **@NeXus_version**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  **Deprecated:** NAPI is frozen.

  Version of NeXus API used in writing the file.

  Note that this is different from the version of the
  base class or application definition version number.            

- **@NeXus_repository**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  A repository containing the application definitions
  used for creating this file.
  If the ``NeXus_release`` attribute contains a commit distance and hash,
  this should refer to this repository.

- **@NeXus_release**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  The version of NeXus definitions used in writing the file. This can either be a date-based
  NeXus release (e.g., YYYY.MM), see https://github.com/nexusformat/definitions/releases or
  a version tag that includes additional development information, such as a commit distance and
  a Git hash. This is typically formatted as  `vYYYY.MM.post1.dev<commit-distance>-g<git-hash>`,
  where `YYYY.MM` refers to the base version of the NeXus definitions. `post1.dev<commit-distance>` 
  indicates that the definitions are based on a commit after the base version (post1), with
  `<commit-distance>` being the number of commits since that version. `g<git-hash>` is the 
  abbreviated Git hash that identifies the specific commit of the definitions being used.

  If the version includes both a commit distance and a Git hash, the ``NeXus_repository`` 
  attribute must be included, specifying the URL of the repository containing that version.

- **@HDF_version**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Version of HDF (version 4) library used in writing the file

- **@HDF5_Version**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Version of HDF5 library used in writing the file.

  Note this attribute is spelled with uppercase "V",
  different than other version attributes.

- **@XML_version**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Version of XML support library used in writing the XML file

- **@h5py_version**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Version of h5py Python package used in writing the file

- **@creator**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  facility or program where file originated

- **@creator_version**: attribute, ``NX_CHAR``, *optional*

  inherited from :ref:`NXroot`; *provisional:* Q1

  Version of facility or program used in writing the file

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

- **ENTRY** (any name): group, :ref:`NXentry`, *required [1..∞]*

  inherited from :ref:`NXroot`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1, Q2, Q11

  entries

  - **DATA** (any name): group, :ref:`NXdata`, *required [1..∞]*

    inherited from :ref:`NXobject`; refined by :ref:`NXentry`, :ref:`NXdemo_phase1`; *provisional:* Q1, Q2, Q11

    The data group

    .. note:: Before the NIAC2016 meeting [#]_, at least one
       :ref:`NXdata` group was required in each :ref:`NXentry` group.
       At the NIAC2016 meeting, it was decided to make :ref:`NXdata`
       an optional group in :ref:`NXentry` groups for data files that
       do not use an application definition.
       It is recommended strongly that all NeXus data files provide
       a NXdata group.
       It is permissible to omit the NXdata group only when
       defining the default plot is not practical or possible
       from the available data.

       For example, neutron event data may not have anything that
       makes a useful plot without extensive processing.

       Certain application definitions override this decision and
       require an :ref:`NXdata` group
       in the :ref:`NXentry` group.  The ``minOccurs=0`` attribute
       in the application definition will indicate the
       :ref:`NXdata` group
       is optional, otherwise, it is required.

       .. [#] NIAC2016:
          https://www.nexusformat.org/NIAC2016.html,
          https://github.com/nexusformat/NIAC/issues/16

    - **@signal**: attribute, ``NX_CHAR``, *required*

      inherited from :ref:`NXdata`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1, Q2

      Allowed values: ``mu``

      .. index:: find the default plottable data
      .. index:: plotting
      .. index:: signal attribute value

      The value is the :ref:`name <validItemName>` of the signal that contains
      the default plottable data. This field or link *must* exist and be a direct child
      of this NXdata group.

      It is recommended (as of NIAC2014) to use this attribute
      rather than adding a signal attribute to the field.
      See https://www.nexusformat.org/2014_How_to_find_default_data.html
      for a summary of the discussion.

    - **mu**: dataset, ``NX_FLOAT``, shape [nE], *required*

      *provisional:* Q1, Q2, Q5

    - **energy**: link, *required*

      *provisional:* Q1, Q2, Q8; link to ``ENTRY/INSTRUMENT/monochromator/energy``

    - … and 27 members of :ref:`NXdata`

  - **title**: dataset, ``NX_CHAR``, *recommended*

    inherited from :ref:`NXentry`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1

    Extended title for entry

  - **definition**: dataset, ``NX_CHAR``, *required*

    inherited from :ref:`NXentry`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1, Q2

    Allowed values: ``NXdemo_phase1``

    (alternate use: see same field in :ref:`NXsubentry` for preferred)

    Official NeXus NXDL schema to which this entry conforms which must be
    the name of the NXDL file (case sensitive without the file extension)
    that the NXDL schema is defined in. 

    For example the ``definition`` field for a file that conformed to the 
    *NXarpes.nxdl.xml* definition must contain the string **NXarpes**.

    This field is provided so that :ref:`NXentry` can be the overlay position
    in a NeXus data file for an application definition and its
    set of groups, fields, and attributes.

    *It is advised* to use :ref:`NXsubentry`, instead, as the overlay position.

    - **@version**: attribute, ``NX_CHAR``, *optional*

      inherited from :ref:`NXentry`; *provisional:* Q1

      NXDL version number

    - **@URL**: attribute, ``NX_CHAR``, *optional*

      inherited from :ref:`NXentry`; *provisional:* Q1

      URL of NXDL file

  - **INSTRUMENT** (any name): group, :ref:`NXinstrument`, *required [1..∞]*

    inherited from :ref:`NXentry`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1, Q2, Q11

    - **monochromator**: group, :ref:`NXmonochromator`, *required*

      refines ``MONOCHROMATOR``; *provisional:* Q1, Q2, Q4, Q11

      - **energy**: dataset, ``NX_FLOAT``, units ``NX_ENERGY``, shape [nE], *required*

        inherited from :ref:`NXmonochromator`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1, Q2, Q5

        energy selected

      - … and 39 members of :ref:`NXmonochromator`

    - **counter**: group, :ref:`NXdemo_counter_phase1`, *required*

      *provisional:* Q1, Q2

      - **mode**: dataset, ``NX_CHAR``, *required*

        inherited from :ref:`NXdemo_counter_phase1`; refined by :ref:`NXdemo_phase1`; *provisional:* Q1, Q2

        Allowed values: ``timer``, ``monitor``

        Counting mode.

      - **i0_counts**: dataset, ``NX_INT``, units ``NX_COUNT``, shape [nE], *required*

        refines ``CHANNEL_counts``; *provisional:* Q1, Q2, Q3, Q4, Q5

        Counts of one channel, for example ``i0_counts``.

      - … and 14 members of :ref:`NXdemo_counter_phase1`

    - … and 44 members of :ref:`NXinstrument`

  - … and 36 members of :ref:`NXentry`

