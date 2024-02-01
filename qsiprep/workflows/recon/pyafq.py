"""
PyAFQ tractometry and visualization
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. autofunction:: init_pyafq_wf

"""
import nipype.pipeline.engine as pe
import nipype.interfaces.utility as niu
import logging
import AFQ
import AFQ.utils.bin as afb
from qsiprep.interfaces.pyafq import PyAFQRecon
from ...interfaces.interchange import recon_workflow_input_fields
from ...interfaces.bids import ReconDerivativesDataSink
LOGGER = logging.getLogger('nipype.workflow')


def _parse_qsiprep_params_dict(params_dict):
    arg_dict = afb.func_dict_to_arg_dict()
    kwargs = {}

    special_args = {
        "CLEANING": "clean_params",
        "SEGMENTATION": "segmentation_params",
        "TRACTOGRAPHY": "tracking_params"}

    for section, args in arg_dict.items():
        if section == "AFQ_desc":
            continue
        for arg, arg_info in args.items():
            if arg in special_args.keys():
                kwargs[special_args[arg]] = {}
                for actual_arg in arg_info.keys():
                    if actual_arg in params_dict:
                        kwargs[special_args[arg]][actual_arg] = afb.toml_to_val(
                            params_dict[actual_arg])
            else:
                if arg in params_dict:
                    kwargs[arg] = afb.toml_to_val(params_dict[arg])

    for ignore_param in afb.qsi_prep_ignore_params:
        kwargs.pop(ignore_param, None)

    return kwargs


def init_pyafq_wf(omp_nthreads, available_anatomical_data,
                  name="afq", output_suffix="", params={}):
    """Run PyAFQ on some qsiprep outputs

    Inputs

        *qsiprep outputs*

    Outputs
        profiles_csv
            CSV file containing the tract profiles generated by pyAFQ.

    """
    inputnode = pe.Node(niu.IdentityInterface(
        fields=recon_workflow_input_fields + ['tck_file']),
        name="inputnode")
    outputnode = pe.Node(
        niu.IdentityInterface(fields=['afq_dir', 'recon_scalars']),
        name="outputnode")
    outputnode.inputs.recon_scalars=[]

    kwargs = _parse_qsiprep_params_dict(params)
    kwargs["omp_nthreads"] = omp_nthreads
    run_afq = pe.Node(PyAFQRecon(kwargs=kwargs), name='run_afq')
    workflow = pe.Workflow(name=name)
    if params.get("use_external_tracking", False):
        workflow.connect([
            (inputnode, run_afq, [('tck_file', 'tck_file')]),
        ])
    workflow.connect([
        (inputnode, run_afq, [
            ('dwi_file', 'dwi_file'),
            ('bval_file', 'bval_file'),
            ('bvec_file', 'bvec_file'),
            ('dwi_mask', 'mask_file'),
            ('t1_2_mni_reverse_transform', 'itk_file')]),
        (run_afq, outputnode, [('afq_dir', 'afq_dir')])
    ])
    if output_suffix:
        # Save the output in the outputs directory
        ds_afq = pe.Node(
            ReconDerivativesDataSink(),
            name='ds_' + name,
            run_without_submitting=True)
        workflow.connect(run_afq, 'afq_dir', ds_afq, 'in_file')

    workflow.__desc__ = (
        f"PyAFQ run on version {AFQ.__version__}"
        f" with the following configuration: {str(kwargs)}")
    return workflow
