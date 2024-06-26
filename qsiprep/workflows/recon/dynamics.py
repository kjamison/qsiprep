"""
Dynamics and Controllability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autofunction:: init_controllability_wf

"""

import logging

import nipype.interfaces.utility as niu
import nipype.pipeline.engine as pe

from ...interfaces.interchange import recon_workflow_input_fields
from qsiprep.interfaces.bids import ReconDerivativesDataSink
from qsiprep.interfaces.connectivity import Controllability

LOGGER = logging.getLogger("nipype.workflow")


def init_controllability_wf(name="controllability", qsirecon_suffix="", params={}, **kwargs):
    """Calculates network controllability from connectivity matrices.

    Calculates modal and average controllability using the method of Gu et al. 2015.

    Inputs

        matfile
            MATLAB format connectivity matrices from DSI Studio connectivity, MRTrix
            connectivity or Dipy Connectivity.

    Outputs

        matfile
            MATLAB format controllability values for each node in each connectivity matrix
            in the input file.


    """
    inputnode = pe.Node(
        niu.IdentityInterface(fields=recon_workflow_input_fields + ["matfile"]), name="inputnode"
    )
    outputnode = pe.Node(niu.IdentityInterface(fields=["matfile"]), name="outputnode")
    plot_reports = params.pop("plot_reports", True)  # noqa: F841

    calc_control = pe.Node(Controllability(**params), name="calc_control")
    workflow = pe.Workflow(name=name)
    workflow.connect([
        (inputnode, calc_control, [('matfile', 'matfile')]),
        (calc_control, outputnode, [('controllability', 'matfile')])
    ])  # fmt:skip
    if qsirecon_suffix:
        # Save the output in the outputs directory
        ds_control = pe.Node(
            ReconDerivativesDataSink(qsirecon_suffix=qsirecon_suffix, suffix="control"),
            name="ds_" + name,
            run_without_submitting=True,
        )
        workflow.connect(calc_control, 'controllability',
                         ds_control, 'in_file')  # fmt:skip
    return workflow
