#!/usr/bin/env python

# Script for performing DWI pre-processing using FSL 5.0 tools eddy / topup / applytopup

# This script is generally one of the first operations that will be applied to diffusion image data. The precise details of how this image pre-processing takes place depends heavily on the DWI acquisition; specifically, the presence or absence of reversed phase-encoding data for the purposes of EPI susceptibility distortion correction.

# The script is capable of handling a wide range of DWI acquisitions with respect to the design of phase encoding directions. This is dependent upon information regarding the phase encoding being embedded within theimage headers. The relevant information should be captured by MRtrix when importing DICOM images; it should also be the case for BIDS-compatible datasets. If the user expects this information to be present within the image headers, the -rpe_header option must be specified.

# If however such information is not present in the image headers, then it is also possible for the user to manually specify the relevant information regarding phase encoding. This involves the following information:
# * The fundamental acquisition protocol design regarding phase encoding. There are three common acquisition designs that are supported:
#   1. All DWI volumes acquired using the same phase encode parameters, and no additional volumes acquired for the purpose of estimating the inhomogeneity field. In this case, eddy will only perform motion and eddy current distortion correction. This configuration is specified using the -rpe_none option.
#   2. All DWI volumes acquired using the same phase encode parameters; but for the purpose of estimating the inhomogeneity field (and subsequently correcting the resulting distortions in the DWIs), an additional pair (or multiple pairs) of image volumes are acquired, where the first volume(s) has the same phase encoding parameters as the input DWI series, and the second volume(s) has precisely the opposite phase encoding. This configuration is specified using the -rpe_pair option; and the user must additionally provide those images to be used for field estimation using the -se_epi option.
#   3. Every DWI gradient direction is acquired twice: once with one phase encoding configuration, and again using the opposite phase encode direction. The goal here is to combine each pair of images into a single DWI volume per gradient direction, where that recombination takes advantage of the information gained from having two volumes where the signal is distorted in opposite directions in the presence of field inhomogeneity.
# * The (primary) direction of phase encoding. In cases where opposing phase encoding is part of the acquisition protocol (i.e. the reversed phase-encode pair in case 2 above, and all of the DWIs in case 3 above), the -pe_dir option specifies the phase encode direction of the _first_ volume in the relevant volume pair; the second is assumed to be the exact opposite.
# * The total readout time of the EPI acquisition. This affects the magnitude of the image distortion for a given field inhomogeneity. If this information is not provided via the -readout_time option, then a 'sane' default of 0.1s will be assumed. Note that this is not actually expected to influence the estimation of the field; it will result in the field inhomogeneity estimation being scaled by some factor, but as long as it uses the same sane default for the DWIs, the distortion correction should operate as expected.

# Make the corresponding MRtrix3 Python libraries available
import inspect, os, sys
lib_folder = os.path.realpath(
    os.path.join(
        os.path.dirname(os.path.realpath(inspect.getfile(inspect.currentframe()))),
        os.pardir, 'lib'))
if not os.path.isdir(lib_folder):
    sys.stderr.write('Unable to locate MRtrix3 Python libraries')
    sys.exit(1)
sys.path.insert(0, lib_folder)

import math, itertools, shutil
from mrtrix3 import app, file, fsl, image, path, phaseEncoding, run  #pylint: disable=redefined-builtin

app.init(
    'Robert E. Smith (robert.smith@florey.edu.au)',
    'Perform diffusion image pre-processing using FSL\'s eddy tool; including inhomogeneity distortion correction using FSL\'s topup tool if possible'
)
app.cmdline.addDescription(
    'Note that this script does not perform any explicit registration between images provided to topup via the -se_epi option, and the DWI volumes provided to eddy. In some instances (motion between acquisitions) this can result in erroneous application of the inhomogeneity field during distortion correction. If this could potentially be a problem for your data, a possible solution is to insert the first b=0 DWI volume to be the first volume of the image file provided via the -se_epi option. This will hopefully be addressed within the script itself in a future update.'
)
app.cmdline.addCitation(
    '',
    'Andersson, J. L. & Sotiropoulos, S. N. An integrated approach to correction for off-resonance effects and subject movement in diffusion MR imaging. NeuroImage, 2015, 125, 1063-1078',
    True)
app.cmdline.addCitation(
    '',
    'Smith, S. M.; Jenkinson, M.; Woolrich, M. W.; Beckmann, C. F.; Behrens, T. E.; Johansen-Berg, H.; Bannister, P. R.; De Luca, M.; Drobnjak, I.; Flitney, D. E.; Niazy, R. K.; Saunders, J.; Vickers, J.; Zhang, Y.; De Stefano, N.; Brady, J. M. & Matthews, P. M. Advances in functional and structural MR image analysis and implementation as FSL. NeuroImage, 2004, 23, S208-S219',
    True)
app.cmdline.addCitation(
    'If performing recombination of diffusion-weighted volume pairs with opposing phase encoding directions',
    'Skare, S. & Bammer, R. Jacobian weighting of distortion corrected EPI data. Proceedings of the International Society for Magnetic Resonance in Medicine, 2010, 5063',
    True)
app.cmdline.addCitation(
    'If performing EPI susceptibility distortion correction',
    'Andersson, J. L.; Skare, S. & Ashburner, J. How to correct susceptibility distortions in spin-echo echo-planar images: application to diffusion tensor imaging. NeuroImage, 2003, 20, 870-888',
    True)
app.cmdline.addCitation(
    'If including "--repol" in -eddy_options input',
    'Andersson, J. L. R.; Graham, M. S.; Zsoldos, E. & Sotiropoulos, S. N. Incorporating outlier detection and replacement into a non-parametric framework for movement and distortion correction of diffusion MR images. NeuroImage, 2016, 141, 556-572',
    True)
app.cmdline.addCitation(
    'If including "--mporder" in -eddy_options input',
    'Andersson, J. L. R.; Graham, M. S.; Drobnjak, I.; Zhang, H.; Filippini, N. & Bastiani, M. Towards a comprehensive framework for movement and distortion correction of diffusion MR images: Within volume movement. NeuroImage, 2017, 152, 450-466',
    True)
app.cmdline.add_argument('input', help='The input DWI series to be corrected')
app.cmdline.add_argument('output', help='The output corrected image series')
grad_export_options = app.cmdline.add_argument_group(
    'Options for exporting the diffusion gradient table')
grad_export_options.add_argument(
    '-export_grad_mrtrix',
    metavar='grad',
    help='Export the final gradient table in MRtrix format')
grad_export_options.add_argument(
    '-export_grad_fsl',
    nargs=2,
    metavar=('bvecs', 'bvals'),
    help='Export the final gradient table in FSL bvecs/bvals format')
app.cmdline.flagMutuallyExclusiveOptions(['export_grad_mrtrix', 'export_grad_fsl'])
grad_import_options = app.cmdline.add_argument_group(
    'Options for importing the diffusion gradient table')
grad_import_options.add_argument(
    '-grad', help='Provide a gradient table in MRtrix format')
grad_import_options.add_argument(
    '-fslgrad',
    nargs=2,
    metavar=('bvecs', 'bvals'),
    help='Provide a gradient table in FSL bvecs/bvals format')
app.cmdline.flagMutuallyExclusiveOptions(['grad', 'fslgrad'])
options = app.cmdline.add_argument_group('Other options for the dwipreproc script')
options.add_argument(
    '-pe_dir',
    metavar=('PE'),
    help=
    'Manually specify the phase encoding direction of the input series; can be a signed axis number (e.g. -0, 1, +2), an axis designator (e.g. RL, PA, IS), or NIfTI axis codes (e.g. i-, j, k)'
)
options.add_argument(
    '-readout_time',
    metavar=('time'),
    type=float,
    help='Manually specify the total readout time of the input series (in seconds)')
options.add_argument(
    '-se_epi',
    metavar=('image'),
    help=
    'Provide an additional image series consisting of spin-echo EPI images, which is to be used exclusively by topup for estimating the inhomogeneity field (i.e. it will not form part of the output image series)'
)
options.add_argument(
    '-align_seepi',
    action='store_true',
    help=
    'Achieve alignment between the SE-EPI images used for inhomogeneity field estimation, and the DWIs, by inserting the first DWI b=0 volume to the SE-EPI series. Only use this option if the input SE-EPI images have identical image contrast to the b=0 images present in the DWI series.'
)
options.add_argument(
    '-json_import',
    metavar=('file'),
    help=
    'Import image header information from an associated JSON file (may be necessary to determine phase encoding information)'
)
options.add_argument(
    '-topup_options',
    metavar=('TopupOptions'),
    help=
    'Manually provide additional command-line options to the topup command (provide a string within quotation marks that contains at least one space, even if only passing a single command-line option to topup)'
)
options.add_argument(
    '-eddy_options',
    metavar=('EddyOptions'),
    help=
    'Manually provide additional command-line options to the eddy command (provide a string within quotation marks that contains at least one space, even if only passing a single command-line option to eddy)'
)
options.add_argument(
    '-eddyqc_text',
    metavar=('directory'),
    help=
    'Copy the various text-based statistical outputs generated by eddy into an output directory'
)
options.add_argument(
    '-eddyqc_all',
    metavar=('directory'),
    help='Copy ALL outputs generated by eddy (including images) into an output directory')
rpe_options = app.cmdline.add_argument_group(
    'Options for specifying the acquisition phase-encoding design; note that one of the -rpe_* options MUST be provided'
)
rpe_options.add_argument(
    '-rpe_none',
    action='store_true',
    help=
    'Specify that no reversed phase-encoding image data is being provided; eddy will perform eddy current and motion correction only'
)
rpe_options.add_argument(
    '-rpe_pair',
    action='store_true',
    help=
    'Specify that a set of images (typically b=0 volumes) will be provided for use in inhomogeneity field estimation only (using the -se_epi option). It is assumed that the FIRST volume(s) of this image has the SAME phase-encoding direction as the input DWIs, and the LAST volume(s) has precisely the OPPOSITE phase encoding'
)
rpe_options.add_argument(
    '-rpe_all',
    action='store_true',
    help=
    'Specify that ALL DWIs have been acquired with opposing phase-encoding; this information will be used to perform a recombination of image volumes (each pair of volumes with the same b-vector but different phase encoding directions will be combined together into a single volume). It is assumed that the SECOND HALF of the volumes in the input DWIs have corresponding diffusion sensitisation directions to the FIRST HALF, but were acquired using precisely the opposite phase-encoding direction'
)
rpe_options.add_argument(
    '-rpe_header',
    action='store_true',
    help=
    'Specify that the phase-encoding information can be found in the image header(s), and that this is the information that the script should use'
)
app.cmdline.flagMutuallyExclusiveOptions(
    ['rpe_none', 'rpe_pair', 'rpe_all', 'rpe_header'], True)
app.cmdline.flagMutuallyExclusiveOptions(
    ['rpe_none', 'se_epi'],
    False)  # May still technically provide -se_epi even with -rpe_all
app.cmdline.flagMutuallyExclusiveOptions(
    ['rpe_header', 'pe_dir'], False
)  # Can't manually provide phase-encoding direction if expecting it to be in the header
app.cmdline.flagMutuallyExclusiveOptions(
    ['rpe_header', 'readout_time'],
    False)  # Can't manually provide readout time if expecting it to be in the header
app.cmdline.flagMutuallyExclusiveOptions(['eddyqc_text', 'eddyqc_all'], False)
app.parse()

if app.isWindows():
    app.error('Script cannot run on Windows due to FSL dependency')

image.check3DNonunity(path.fromUser(app.args.input, False))

PE_design = ''
if app.args.rpe_none:
    PE_design = 'None'
elif app.args.rpe_pair:
    PE_design = 'Pair'
    if not app.args.se_epi:
        app.error(
            'If using the -rpe_pair option, the -se_epi option must be used to provide the spin-echo EPI data to be used by topup'
        )
elif app.args.rpe_all:
    PE_design = 'All'
elif app.args.rpe_header:
    PE_design = 'Header'
else:
    app.error('Must explicitly specify phase-encoding acquisition design (even if none)')

if app.args.align_seepi and not app.args.se_epi:
    app.error(
        '-align_seepi option is only applicable when the -se_epi option is also used')

fsl_path = os.environ.get('FSLDIR', '')
if not fsl_path:
    app.error(
        'Environment variable FSLDIR is not set; please run appropriate FSL configuration script'
    )

if not PE_design == 'None':
    topup_config_path = os.path.join(fsl_path, 'etc', 'flirtsch', 'b02b0.cnf')
    if not os.path.isfile(topup_config_path):
        app.error(
            'Could not find necessary default config file for FSL topup command\n(expected location: '
            + topup_config_path + ')')
    topup_cmd = fsl.exeName('topup')
    applytopup_cmd = fsl.exeName('applytopup')

if not fsl.eddyBinary(True) and not fsl.eddyBinary(False):
    app.error('Could not find any version of FSL eddy command')
fsl_suffix = fsl.suffix()
app.checkOutputPath(app.args.output)

# Export the gradient table to the path requested by the user if necessary
grad_export_option = ''
if app.args.export_grad_mrtrix:
    grad_export_option = ' -export_grad_mrtrix ' + path.fromUser(
        app.args.export_grad_mrtrix, True)
    app.checkOutputPath(path.fromUser(app.args.export_grad_mrtrix, False))
elif app.args.export_grad_fsl:
    grad_export_option = ' -export_grad_fsl ' + path.fromUser(
        app.args.export_grad_fsl[0], True) + ' ' + path.fromUser(
            app.args.export_grad_fsl[1], True)
    app.checkOutputPath(path.fromUser(app.args.export_grad_fsl[0], False))
    app.checkOutputPath(path.fromUser(app.args.export_grad_fsl[1], False))

eddyqc_path = None
eddyqc_files = [ 'eddy_parameters', 'eddy_movement_rms', 'eddy_restricted_movement_rms', \
                 'eddy_post_eddy_shell_alignment_parameters', 'eddy_post_eddy_shell_PE_translation_parameters', \
                 'eddy_outlier_report', 'eddy_outlier_map', 'eddy_outlier_n_stdev_map', 'eddy_outlier_n_sqr_stdev_map', \
                 'eddy_movement_over_time' ]
if app.args.eddyqc_text:
    eddyqc_path = path.fromUser(app.args.eddyqc_text, False)
elif app.args.eddyqc_all:
    eddyqc_path = path.fromUser(app.args.eddyqc_all, False)
    eddyqc_files.extend([
        'eddy_outlier_free_data.nii.gz', 'eddy_cnr_maps.nii.gz', 'eddy_residuals.nii.gz'
    ])
if eddyqc_path:
    if os.path.exists(eddyqc_path):
        if os.path.isdir(eddyqc_path):
            if any([
                    os.path.exists(os.path.join(eddyqc_path, filename))
                    for filename in eddyqc_files
            ]):
                if app.forceOverwrite:
                    app.warn(
                        'Output eddy QC directory already contains relevant files; these will be overwritten on completion'
                    )
                else:
                    app.error(
                        'Output eddy QC directory already contains relevant files (use -force to override)'
                    )
        else:
            if app.forceOverwrite:
                app.warn(
                    'Target for eddy QC output is not a directory; it will be overwritten on completion'
                )
            else:
                app.error(
                    'Target for eddy QC output exists, and is not a directory (use -force to override)'
                )

eddy_manual_options = ''
if app.args.eddy_options:
    # Initially process as a list; we'll convert back to a string later
    eddy_manual_options = app.args.eddy_options.strip().split()

# Convert all input images into MRtrix format and store in temprary directory first
app.makeTempDir()

grad_option = ''
if app.args.grad:
    grad_option = ' -grad ' + path.fromUser(app.args.grad, True)
elif app.args.fslgrad:
    grad_option = ' -fslgrad ' + path.fromUser(
        app.args.fslgrad[0], True) + ' ' + path.fromUser(app.args.fslgrad[1], True)
json_option = ''
if app.args.json_import:
    json_option = ' -json_import ' + path.fromUser(app.args.json_import, True)
run.command('mrconvert ' + path.fromUser(app.args.input, True) + ' ' +
            path.toTemp('dwi.mif', True) + grad_option + json_option)
if app.args.se_epi:
    image.check3DNonunity(path.fromUser(app.args.se_epi, False))
    run.command('mrconvert ' + path.fromUser(app.args.se_epi, True) + ' ' +
                path.toTemp('se_epi.mif', True))

app.gotoTempDir()

# Get information on the input images, and check their validity
dwi_header = image.Header('dwi.mif')
if not len(dwi_header.size()) == 4:
    app.error('Input DWI must be a 4D image')
dwi_num_volumes = dwi_header.size()[3]
app.var(dwi_num_volumes)
dwi_num_slices = dwi_header.size()[2]
app.var(dwi_num_slices)
dwi_pe_scheme = phaseEncoding.getScheme(dwi_header)
if app.args.se_epi:
    se_epi_header = image.Header('se_epi.mif')
    # This doesn't necessarily apply any more: May be able to combine e.g. a P>>A from -se_epi with an A>>P b=0 image from the DWIs
    #  if not len(se_epi_header.size()) == 4:
    #    app.error('File provided using -se_epi option must contain more than one image volume')
    se_epi_pe_scheme = phaseEncoding.getScheme(se_epi_header)
if 'dw_scheme' not in dwi_header.keyval():
    app.error('No diffusion gradient table found')
grad = dwi_header.keyval()['dw_scheme']
if not len(grad) == dwi_num_volumes:
    app.error('Number of lines in gradient table (' + str(len(grad)) +
              ') does not match input image (' + str(dwi_num_volumes) +
              ' volumes); check your input data')

# Check the manual options being passed to eddy, ensure they make sense
eddy_mporder = any(s.startswith('--mporder') for s in eddy_manual_options)
if eddy_mporder:
    if 'SliceEncodingDirection' in dwi_header.keyval():
        slice_encoding_direction = dwi_header.keyval()['SliceEncodingDirection']
        app.var(slice_encoding_direction)
        if not slice_encoding_direction.startswith('k'):
            app.error(
                'DWI header indicates that 3rd spatial axis is not the slice axis; this is not yet compatible with --mporder option in eddy, nor supported in dwipreproc'
            )
        slice_encoding_direction = image.axis2dir(slice_encoding_direction)
    else:
        app.console(
            'No slice encoding direction information present; assuming third axis corresponds to slices'
        )
        slice_encoding_direction = [0, 0, 1]
if '--resamp=lsr' in eddy_manual_options:
    app.error(
        'dwipreproc does not currently support least-squares reconstruction; this cannot be simply passed via -eddy_options'
    )
if eddy_mporder:
    slspec_option = [s for s in eddy_manual_options if s.startswith('--slspec')]
    slice_groups = []
    slice_timing = []
    if len(slspec_option) > 1:
        app.error(
            '--slspec option appears more than once in -eddy_options input; cannot import slice timing'
        )
    elif len(slspec_option) == 1:
        slspec_file_path = path.fromUser(slspec_option[0][9:], False)
        if os.path.isfile(slspec_file_path):
            # Since there's a chance that we may need to pad this info, we can't just copy this file
            #   to the temporary directory...
            with open(slspec_file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        slice_groups.append([int(value) for value in line.split()])
            app.var(slice_groups)
            # Remove this entry from eddy_manual_options; it'll be inserted later, with the
            #   path to the new slspec file
            eddy_manual_options = [
                s for s in eddy_manual_options if not s.startswith('--slspec')
            ]
        else:
            app.error(
                'Unable to find \'slspec\' file provided via -eddy_options \" ... --slspec=/path/to/file ... \" (expected location: '
                + slspec_file_path + ')')
    else:
        if 'SliceTiming' not in dwi_header.keyval():
            app.error(
                'Cannot perform slice-to-volume correction in eddy: No slspec file provided, and no slice timing information present in header'
            )
        slice_timing = dwi_header.keyval()['SliceTiming'][0]
        app.var(slice_timing)
        if len(slice_timing) != dwi_num_slices:
            app.error(
                'Cannot use slice timing information in image header for slice-to-volume correction: Number of entries ('
                + len(slice_timing) + ') does not match number of slices (' +
                dwi_header.size()[2] + ')')

# Use new features of dirstat to query the quality of the diffusion acquisition scheme
# Need to know the mean b-value in each shell, and the asymmetry value of each shell
# But don't bother testing / warning the user if they're already controlling for this
if not app.args.eddy_options or not any(
        s.startswith('--slm=') for s in app.args.eddy_options.split()):
    shell_bvalues = [
        int(round(float(value)))
        for value in image.mrinfo('dwi.mif', 'shell_bvalues').split()
    ]
    shell_asymmetry = [
        float(value)
        for value in run.command('dirstat dwi.mif -output asym')[0].splitlines()
    ]
    # dirstat will skip any b=0 shell by default; therefore for correspondence between
    #   shell_bvalues and shell_symmetry, need to remove any b=0 from the former
    if len(shell_bvalues) == len(shell_asymmetry) + 1:
        shell_bvalues = shell_bvalues[1:]
    elif len(shell_bvalues) != len(shell_asymmetry):
        app.error('Number of b-values reported by mrinfo (' + str(len(shell_bvalues)) +
                  ') does not match number of outputs provided by dirstat (' +
                  str(len(shell_asymmetry)) + ')')
    for b, s in zip(shell_bvalues, shell_asymmetry):
        if s >= 0.1:
            app.warn('sampling of b=' + str(b) + ' shell is ' + ('strongly' if s >= 0.4 else 'moderately') + \
                     ' asymmetric; distortion correction may benefit from use of: ' + \
                     '-eddy_options " ... --slm=linear ... "')

# Since we want to access user-defined phase encoding information regardless of whether or not
#   such information is present in the header, let's grab it here
manual_pe_dir = None
if app.args.pe_dir:
    manual_pe_dir = [float(i) for i in phaseEncoding.direction(app.args.pe_dir)]
app.var(manual_pe_dir)
manual_trt = None
if app.args.readout_time:
    manual_trt = float(app.args.readout_time)
app.var(manual_trt)

do_topup = (not PE_design == 'None')


def grads_match(one, two):
    # Dot product between gradient directions
    # First, need to check for zero-norm vectors:
    # - If both are zero, skip this check
    # - If one is zero and the other is not, volumes don't match
    # - If neither is zero, test the dot product
    if any([val for val in one[0:3]]):
        if not any([val for val in two[0:3]]):
            return False
        dot_product = one[0] * two[0] + one[1] * two[1] + one[2] * two[2]
        if abs(dot_product) < 0.999:
            return False
    elif any([val for val in two[0:3]]):
        return False
    # b-value
    if abs(one[3] - two[3]) > 10.0:
        return False
    return True


# Manually generate a phase-encoding table for the input DWI based on user input
dwi_manual_pe_scheme = None
se_epi_manual_pe_scheme = None
auto_trt = 0.1
dwi_auto_trt_warning = False
if manual_pe_dir:

    if manual_trt:
        trt = manual_trt
    else:
        trt = auto_trt
        dwi_auto_trt_warning = True

    # Still construct the manual PE scheme even with 'None' or 'Pair':
    #   there may be information in the header that we need to compare against
    if PE_design == 'None':
        line = list(manual_pe_dir)
        line.append(trt)
        dwi_manual_pe_scheme = [line] * dwi_num_volumes
        app.var(dwi_manual_pe_scheme)

    # With 'Pair', also need to construct the manual scheme for SE EPIs
    elif PE_design == 'Pair':
        line = list(manual_pe_dir)
        line.append(trt)
        dwi_manual_pe_scheme = [line] * dwi_num_volumes
        app.var(dwi_manual_pe_scheme)
        se_epi_num_volumes = se_epi_header.size()[3]
        if se_epi_num_volumes % 2:
            app.error(
                'If using -rpe_pair option, image provided using -se_epi must contain an even number of volumes'
            )
        # Assume that first half of volumes have same direction as series;
        #   second half have the opposite direction
        se_epi_manual_pe_scheme = [line] * int(se_epi_num_volumes / 2)
        line = [(-i if i else 0.0) for i in manual_pe_dir]
        line.append(trt)
        se_epi_manual_pe_scheme.extend([line] * int(se_epi_num_volumes / 2))
        app.var(se_epi_manual_pe_scheme)

    # If -rpe_all, need to scan through grad and figure out the pairings
    # This will be required if relying on user-specified phase encode direction
    # It will also be required at the end of the script for the manual recombination
    # Update: The possible permutations of volume-matched acquisition is limited within the
    #   context of the -rpe_all option. In particular, the potential for having more
    #   than one b=0 volume within each half means that it is not possible to permit
    #   arbitrary ordering of those pairs, since b=0 volumes would then be matched
    #   despite having the same phase-encoding direction. Instead, explicitly enforce
    #   that volumes must be matched between the first and second halves of the DWI data.
    elif PE_design == 'All':
        if dwi_num_volumes % 2:
            app.error(
                'If using -rpe_all option, input image must contain an even number of volumes'
            )
        grads_matched = [dwi_num_volumes] * dwi_num_volumes
        grad_pairs = []
        app.debug('Commencing gradient direction matching; ' + str(dwi_num_volumes) +
                  ' volumes')
        for index1 in range(int(dwi_num_volumes / 2)):
            if grads_matched[index1] == dwi_num_volumes:  # As yet unpaired
                for index2 in range(int(dwi_num_volumes / 2), dwi_num_volumes):
                    if grads_matched[index2] == dwi_num_volumes:  # Also as yet unpaired
                        if grads_match(grad[index1], grad[index2]):
                            grads_matched[index1] = index2
                            grads_matched[index2] = index1
                            grad_pairs.append([index1, index2])
                            app.debug('Matched volume ' + str(index1) + ' with ' +
                                      str(index2) + ': ' + str(grad[index1]) + ' ' +
                                      str(grad[index2]))
                            break
                else:
                    app.error(
                        'Unable to determine matching reversed phase-encode direction volume for DWI volume '
                        + str(index1))
        if not len(grad_pairs) == dwi_num_volumes / 2:
            app.error(
                'Unable to determine complete matching DWI volume pairs for reversed phase-encode combination'
            )
        # Construct manual PE scheme here:
        #   Regardless of whether or not there's a scheme in the header, need to have it:
        #   if there's one in the header, want to compare to the manually-generated one
        dwi_manual_pe_scheme = []
        for index in range(0, dwi_num_volumes):
            line = list(manual_pe_dir)
            if index >= int(dwi_num_volumes / 2):
                line = [(-i if i else 0.0) for i in line]
            line.append(trt)
            dwi_manual_pe_scheme.append(line)
        app.var(dwi_manual_pe_scheme)

else:  # No manual phase encode direction defined

    if not PE_design == 'Header':
        app.error(
            'If not using -rpe_header, phase encoding direction must be provided using the -pe_dir option'
        )


def scheme_dirs_match(one, two):
    for line_one, line_two in zip(one, two):
        if not line_one[0:3] == line_two[0:3]:
            return False
    return True


def scheme_times_match(one, two):
    for line_one, line_two in zip(one, two):
        if abs(line_one[3] - line_two[3]) > 5e-3:
            return False
    return True


# Determine whether or not the phase encoding table generated manually should be used
#   (possibly instead of a table present in the image header)
overwrite_dwi_pe_scheme = False
if dwi_pe_scheme:
    if manual_pe_dir:
        # Compare manual specification to that read from the header;
        #   overwrite & give warning to user if they differ
        # Bear in mind that this could even be the case for -rpe_all;
        #   relying on earlier code having successfully generated the 'appropriate'
        #   PE scheme for the input volume based on the diffusion gradient table
        if not scheme_dirs_match(dwi_pe_scheme, dwi_manual_pe_scheme):
            app.warn(
                'User-defined phase-encoding direction design does not match what is stored in DWI image header; proceeding with user specification'
            )
            overwrite_dwi_pe_scheme = True
    if manual_trt:
        # Compare manual specification to that read from the header
        if not scheme_times_match(dwi_pe_scheme, dwi_manual_pe_scheme):
            app.warn(
                'User-defined total readout time does not match what is stored in DWI image header; proceeding with user specification'
            )
            overwrite_dwi_pe_scheme = True
    if overwrite_dwi_pe_scheme:
        dwi_pe_scheme = dwi_manual_pe_scheme  # May be used later for triggering volume recombination
    else:
        dwi_manual_pe_scheme = None  # To guarantee that these generated data are never used
else:
    # Nothing in the header; rely entirely on user specification
    if PE_design == 'Header':
        app.error('No phase encoding information found in DWI image header')
    if not manual_pe_dir:
        app.error(
            'No phase encoding information provided either in header or at command-line')
    if dwi_auto_trt_warning:
        app.console(
            'Total readout time not provided at command-line; assuming sane default of ' +
            str(auto_trt))
    dwi_pe_scheme = dwi_manual_pe_scheme  # May be needed later for triggering volume recombination

# This may be required by -rpe_all for extracting b=0 volumes while retaining phase-encoding information
import_dwi_pe_table_option = ''
if dwi_manual_pe_scheme:
    with open('dwi_manual_pe_scheme.txt', 'w') as f:
        for line in dwi_manual_pe_scheme:
            f.write(' '.join([str(value) for value in line]) + '\n')
    import_dwi_pe_table_option = ' -import_pe_table dwi_manual_pe_scheme.txt'

# Find the index of the first DWI volume that is a b=0 volume
# This needs to occur at the outermost loop as it is pertinent information
#   not only for the -align_seepi option, but also for when the -se_epi option
#   is not provided at all, and the input top topup is extracted solely from the DWIs
bzero_threshold = 10.0
if 'BZeroThreshold' in app.config:
    bzero_threshold = float(app.config['BZeroThreshold'])
dwi_first_bzero_index = 0
for line in grad:
    if line[3] <= bzero_threshold:
        break
    dwi_first_bzero_index += 1
app.var(dwi_first_bzero_index)

# Deal with the phase-encoding of the images to be fed to topup (if applicable)
overwrite_se_epi_pe_scheme = False
se_epi_path = 'se_epi.mif'
dwi_permute_volumes_pre_eddy_option = ''
dwi_permute_volumes_post_eddy_option = ''
dwi_bzero_added_to_se_epi = False
if app.args.se_epi:

    # Newest version of eddy requires that topup field be on the same grid as the eddy input DWI
    if not image.match(dwi_header, se_epi_header, 3):
        app.console(
            'DWIs and SE-EPI images used for inhomogeneity field estimation are defined on different image grids; '
            'the latter will be automatically re-gridded to match the former')
        new_se_epi_path = 'se_epi_regrid.mif'
        run.command('mrtransform ' + se_epi_path +
                    ' - -interp sinc -template dwi.mif | mrcalc - 0.0 -max ' +
                    new_se_epi_path)
        file.delTemporary(se_epi_path)
        se_epi_path = new_se_epi_path
        se_epi_header = image.Header(se_epi_path)

    # 3 possible sources of PE information: DWI header, topup image header, command-line
    # Any pair of these may conflict, and any one could be absent

    # Have to switch here based on phase-encoding acquisition design
    if PE_design == 'Pair':
        # Criteria:
        #   * If present in own header, ignore DWI header entirely -
        #     - If also provided at command-line, look for conflict & report
        #     - If not provided at command-line, nothing to do
        #   * If _not_ present in own header:
        #     - If provided at command-line, infer appropriately
        #     - If not provided at command-line, but the DWI header has that information, infer appropriately
        if se_epi_pe_scheme:
            if manual_pe_dir:
                if not scheme_dirs_match(se_epi_pe_scheme, se_epi_manual_pe_scheme):
                    app.warn(
                        'User-defined phase-encoding direction design does not match what is stored in SE EPI image header; proceeding with user specification'
                    )
                    overwrite_se_epi_pe_scheme = True
            if manual_trt:
                if not scheme_times_match(se_epi_pe_scheme, se_epi_manual_pe_scheme):
                    app.warn(
                        'User-defined total readout time does not match what is stored in SE EPI image header; proceeding with user specification'
                    )
                    overwrite_se_epi_pe_scheme = True
            if overwrite_se_epi_pe_scheme:
                se_epi_pe_scheme = se_epi_manual_pe_scheme
            else:
                se_epi_manual_pe_scheme = None  # To guarantee that these data are never used
        else:
            overwrite_se_epi_pe_scheme = True
            se_epi_pe_scheme = se_epi_manual_pe_scheme

    elif PE_design == 'All':
        # Criteria:
        #   * If present in own header:
        #     - Nothing to do
        #   * If _not_ present in own header:
        #     - Don't have enough information to proceed
        #     - Is this too harsh? (e.g. Have rules by which it may be inferred from the DWI header / command-line)
        if not se_epi_pe_scheme:
            app.error(
                'If explicitly including SE EPI images when using -rpe_all option, they must come with their own associated phase-encoding information in the image header'
            )

    elif PE_design == 'Header':
        # Criteria:
        #   * If present in own header:
        #       Nothing to do (-pe_dir option is mutually exclusive)
        #   * If _not_ present in own header:
        #       Cannot proceed
        if not se_epi_pe_scheme:
            app.error('No phase-encoding information present in SE-EPI image header')
        # If there is no phase encoding contrast within the SE-EPI series,
        #   try combining it with the DWI b=0 volumes, see if that produces some contrast
        # However, this should probably only be permitted if the -align_seepi option is defined
        se_epi_pe_scheme_has_contrast = 'pe_scheme' in se_epi_header.keyval()
        if not se_epi_pe_scheme_has_contrast:
            if app.args.align_seepi:
                app.console(
                    'No phase-encoding contrast present in SE-EPI images; will examine again after combining with DWI b=0 images'
                )
                new_se_epi_path = os.path.splitext(se_epi_path)[0] + '_dwibzeros.mif'
                # Don't worry about trying to produce a balanced scheme here
                run.command('dwiextract dwi.mif - -bzero | mrcat - se_epi.mif ' +
                            new_se_epi_path + ' -axis 3')
                se_epi_header = image.Header(new_se_epi_path)
                se_epi_pe_scheme_has_contrast = 'pe_scheme' in se_epi_header.keyval()
                if se_epi_pe_scheme_has_contrast:
                    file.delTemporary(se_epi_path)
                    se_epi_path = new_se_epi_path
                    se_epi_pe_scheme = phaseEncoding.getScheme(se_epi_header)
                    dwi_bzero_added_to_se_epi = True
                    # Delay testing appropriateness of the concatenation of these images
                    #   (i.e. differences in contrast) to later
                else:
                    app.error(
                        'No phase-encoding contrast present in SE-EPI images, even after concatenating with b=0 images due to -align_seepi option; '
                        'cannot perform inhomogeneity field estimation')
            else:
                app.error(
                    'No phase-encoding contrast present in SE-EPI images; cannot perform inhomogeneity field estimation'
                )

    if app.args.align_seepi:

        dwi_te = dwi_header.keyval().get('EchoTime')
        se_epi_te = se_epi_header.keyval().get('EchoTime')
        if dwi_te and se_epi_te and dwi_te != se_epi_te:
            app.warn(
                'It appears that the spin-echo EPI images used for inhomogeneity field estimation have a different echo time to the DWIs being corrected. '
                'This may cause issues in estimation of the field, as the first DWI b=0 volume will be added to the input series to topup '
                'due to use of the -align_seepi option.')

        dwi_tr = dwi_header.keyval().get('RepetitionTime')
        se_epi_tr = se_epi_header.keyval().get('RepetitionTime')
        if dwi_tr and se_epi_tr and dwi_tr != se_epi_tr:
            app.warn(
                'It appears that the spin-echo EPI images used for inhomogeneity field estimation have a different repetition time to the DWIs being corrected. '
                'This may cause issues in estimation of the field, as the first DWI b=0 volume will be added to the input series to topup '
                'due to use of the -align_seepi option.')

        dwi_flip = dwi_header.keyval().get('FlipAngle')
        se_epi_flip = se_epi_header.keyval().get('FlipAngle')
        if dwi_flip and se_epi_flip and dwi_flip != se_epi_flip:
            app.warn(
                'It appears that the spin-echo EPI images used for inhomogeneity field estimation have a different flip angle to the DWIs being corrected. '
                'This may cause issues in estimation of the field, as the first DWI b=0 volume will be added to the input series to topup '
                'due to use of the -align_seepi option.')

        # If we are using the -se_epi option, and hence the input images to topup have not come from the DWIs themselves,
        #   we need to insert the first b=0 DWI volume to the start of the topup input image. Otherwise, the field estimated
        #   by topup will not be correctly aligned with the volumes as they are processed by eddy.
        #
        # However, there's also a code path by which we may have already performed this addition.
        # If we have already apliced the b=0 volumes from the DWI input with the SE-EPI image
        #   (due to the absence of phase-encoding contrast in the SE-EPI series), we don't want to
        #   re-attempt such a concatenation; the fact that the DWI b=0 images were inserted ahead of
        #   the SE-EPI images means the alignment issue should be dealt with.

        if dwi_first_bzero_index == len(grad) and not dwi_bzero_added_to_se_epi:

            app.warn(
                'Unable to find b=0 volume in input DWIs to provide alignment between topup and eddy; script will proceed as though the -align_seepi option were not provided'
            )

        # If b=0 volumes from the DWIs have already been added to the SE-EPI image due to an
        #   absence of phase-encoding contrast in the latter, we don't need to perform the following
        elif not dwi_bzero_added_to_se_epi:

            run.command('mrconvert dwi.mif dwi_first_bzero.mif -coord 3 ' +
                        str(dwi_first_bzero_index) + ' -axes 0,1,2')
            dwi_first_bzero_pe = dwi_manual_pe_scheme[
                dwi_first_bzero_index] if overwrite_dwi_pe_scheme else dwi_pe_scheme[
                    dwi_first_bzero_index]

            se_epi_pe_sum = [0, 0, 0]
            se_epi_volume_to_remove = len(se_epi_pe_scheme)
            for index, line in enumerate(se_epi_pe_scheme):
                se_epi_pe_sum = [i + j for i, j in zip(se_epi_pe_sum, line[0:3])]
                if se_epi_volume_to_remove == len(
                        se_epi_pe_scheme) and line[0:3] == dwi_first_bzero_pe[0:3]:
                    se_epi_volume_to_remove = index
            new_se_epi_path = os.path.splitext(se_epi_path)[0] + '_firstdwibzero.mif'
            if (se_epi_pe_sum == [
                    0, 0, 0
            ]) and (se_epi_volume_to_remove < len(se_epi_pe_scheme)):
                app.console(
                    'Balanced phase-encoding scheme detected in SE-EPI series; volume ' +
                    str(se_epi_volume_to_remove) +
                    ' will be removed and replaced with first b=0 from DWIs')
                run.command('mrconvert ' + se_epi_path + ' - -coord 3 ' + ','.join([
                    str(index) for index in range(len(se_epi_pe_scheme))
                    if not index == se_epi_volume_to_remove
                ]) + ' | mrcat dwi_first_bzero.mif - ' + new_se_epi_path + ' -axis 3')
                # Also need to update the phase-encoding scheme appropriately if it's being set manually
                #   (if embedded within the image headers, should be updated through the command calls)
                if se_epi_manual_pe_scheme:
                    first_line = list(manual_pe_dir)
                    first_line.append(trt)
                    new_se_epi_manual_pe_scheme = []
                    new_se_epi_manual_pe_scheme.append(first_line)
                    for index, entry in enumerate(se_epi_manual_pe_scheme):
                        if not index == se_epi_volume_to_remove:
                            new_se_epi_manual_pe_scheme.append(entry)
                    se_epi_manual_pe_scheme = new_se_epi_manual_pe_scheme
            else:
                if se_epi_pe_sum == [
                        0, 0, 0
                ] and se_epi_volume_to_remove == len(se_epi_pe_scheme):
                    app.console(
                        'Phase-encoding scheme of -se_epi image is balanced, but could not find appropriate volume with which to substitute first b=0 volume from DWIs; first b=0 DWI volume will be inserted to start of series, resulting in an unbalanced scheme'
                    )
                else:
                    app.console(
                        'Unbalanced phase-encoding scheme detected in series provided via -se_epi option; first DWI b=0 volume will be inserted to start of series'
                    )
                run.command('mrcat dwi_first_bzero.mif ' + se_epi_path + ' ' +
                            new_se_epi_path + ' -axis 3')
                # Also need to update the phase-encoding scheme appropriately
                if se_epi_manual_pe_scheme:
                    first_line = list(manual_pe_dir)
                    first_line.append(trt)
                    se_epi_manual_pe_scheme = [first_line, se_epi_manual_pe_scheme]

            # Ended branching based on balanced-ness of PE acquisition scheme within SE-EPI volumes
            file.delTemporary(se_epi_path)
            file.delTemporary('dwi_first_bzero.mif')
            se_epi_path = new_se_epi_path

        # Ended branching based on:
        # - Detection of first b=0 volume in DWIs; or
        # - Prior merge of SE-EPI and DWI b=0 volumes due to no phase-encoding contrast in SE-EPI

    # Completed checking for presence of -se_epi option

elif not PE_design == 'None':  # No SE EPI images explicitly provided: In some cases, can extract appropriate b=0 images from DWI

    # If using 'All' or 'Header', and haven't been given any topup images, need to extract the b=0 volumes from the series,
    #   preserving phase-encoding information while doing so
    # Preferably also make sure that there's some phase-encoding contrast in there...
    # With -rpe_all, need to write inferred phase-encoding to file and import before using dwiextract so that the phase-encoding
    #   of the extracted b=0's is propagated to the generated b=0 series
    run.command('mrconvert dwi.mif' + import_dwi_pe_table_option + ' - | dwiextract - ' +
                se_epi_path + ' -bzero')
    se_epi_header = image.Header(se_epi_path)

    # If there's no contrast remaining in the phase-encoding scheme, it'll be written to
    #   PhaseEncodingDirection and TotalReadoutTime rather than pe_scheme
    # In this scenario, we will be unable to run topup, or volume recombination
    if 'pe_scheme' not in se_epi_header.keyval():
        if PE_design == 'All':
            app.error(
                'DWI header indicates no phase encoding contrast between b=0 images; cannot proceed with volume recombination-based pre-processing'
            )
        else:
            app.warn(
                'DWI header indicates no phase encoding contrast between b=0 images; proceeding without inhomogeneity field estimation'
            )
            do_topup = False
            run.function(os.remove, se_epi_path)
            se_epi_path = None
            se_epi_header = None

# If the first b=0 volume in the DWIs is in fact not the first volume (i.e. index zero), we're going to
#   manually place it at the start of the DWI volumes when they are input to eddy, so that the
#   first input volume to topup and the first input volume to eddy are one and the same.
# Note: If at a later date, the statistical outputs from eddy are considered (e.g. motion, outliers),
#   then this volume permutation will need to be taken into account
if dwi_first_bzero_index:
    app.console('First b=0 volume in input DWIs is volume index ' +
                str(dwi_first_bzero_index) + '; '
                'this will be permuted to be the first volume (index 0) when eddy is run')
    dwi_permute_volumes_pre_eddy_option = ' -coord 3 ' + \
                                          str(dwi_first_bzero_index) + \
                                          ',0' + \
                                          (':' + str(dwi_first_bzero_index-1) if dwi_first_bzero_index > 1 else '') + \
                                          (',' + str(dwi_first_bzero_index+1) if dwi_first_bzero_index < dwi_num_volumes-1 else '') + \
                                          (':' + str(dwi_num_volumes-1) if dwi_first_bzero_index < dwi_num_volumes-2 else '')
    dwi_permute_volumes_post_eddy_option = ' -coord 3 1' + \
                                           (':' + str(dwi_first_bzero_index) if dwi_first_bzero_index > 1 else '') + \
                                           ',0' + \
                                           (',' + str(dwi_first_bzero_index+1) if dwi_first_bzero_index < dwi_num_volumes-1 else '') + \
                                           (':' + str(dwi_num_volumes-1) if dwi_first_bzero_index < dwi_num_volumes-2 else '')
    app.var(dwi_permute_volumes_pre_eddy_option, dwi_permute_volumes_post_eddy_option)

# This may be required when setting up the topup call
import_se_epi_manual_pe_table_option = ''
if se_epi_manual_pe_scheme:
    with open('se_epi_manual_pe_scheme.txt', 'w') as f:
        for line in se_epi_manual_pe_scheme:
            f.write(' '.join([str(value) for value in line]) + '\n')
    import_se_epi_manual_pe_table_option = ' -import_pe_table se_epi_manual_pe_scheme.txt'

# Need gradient table if running dwi2mask after applytopup to derive a brain mask for eddy
run.command('mrinfo dwi.mif -export_grad_mrtrix grad.b')

eddy_in_topup_option = ''
dwi_post_eddy_crop_option = ''
dwi_path = 'dwi.mif'
if do_topup:

    # topup will crash if its input image has a spatial dimension with a non-even size;
    #   presumably due to a downsampling by a factor of 2 in a multi-resolution scheme
    # The newest eddy also requires the output from topup and the input DWIs to have the same size;
    #   therefore this restriction applies to the DWIs as well
    # Rather than crop in this case (which would result in a cropped output image),
    #   duplicate the last slice on any problematic axis, and then crop that extra
    #   slice at the output step
    # By this point, if the input SE-EPI images and DWIs are not on the same image grid, the
    #   SE-EPI images have already been re-gridded to DWI image space;
    odd_axis_count = 0
    for axis_size in dwi_header.size()[:3]:
        if int(axis_size % 2):
            odd_axis_count += 1
    if odd_axis_count:
        app.console(
            str(odd_axis_count) + ' spatial ' +
            ('axes of DWIs have' if odd_axis_count > 1 else 'axis of DWIs has') +
            ' non-even size; '
            'this will be automatically padded for compatibility with topup, and the extra slice'
            + ('s' if odd_axis_count > 1 else '') + ' erased afterwards')
        for axis, axis_size in enumerate(dwi_header.size()[:3]):
            if int(axis_size % 2):
                new_se_epi_path = os.path.splitext(se_epi_path)[0] + '_pad' + str(
                    axis) + '.mif'
                run.command('mrconvert ' + se_epi_path + ' -coord ' + str(axis) + ' ' +
                            str(axis_size - 1) + ' - | mrcat ' + se_epi_path + ' - ' +
                            new_se_epi_path + ' -axis ' + str(axis))
                file.delTemporary(se_epi_path)
                se_epi_path = new_se_epi_path
                new_dwi_path = os.path.splitext(dwi_path)[0] + '_pad' + str(axis) + '.mif'
                run.command('mrconvert ' + dwi_path + ' -coord ' + str(axis) + ' ' +
                            str(axis_size - 1) + ' - | mrcat ' + dwi_path + ' - ' +
                            new_dwi_path + ' -axis ' + str(axis))
                file.delTemporary(dwi_path)
                dwi_path = new_dwi_path
                dwi_post_eddy_crop_option += ' -coord ' + str(axis) + ' 0:' + str(
                    axis_size - 1)
                # If we are padding the slice axis, and performing slice-to-volume correction,
                #   then we need to perform the corresponding padding to the slice timing
                if eddy_mporder and slice_encoding_direction[axis]:
                    dwi_num_slices += 1
                    # At this point in the script, this information may be encoded either within
                    #   the slice timing vector (as imported from the image header), or as
                    #   slice groups (i.e. in the format expected by eddy). How these data are
                    #   stored affects how the padding is performed.
                    if slice_timing:
                        slice_timing.append(slice_timing[-1])
                    elif slice_groups:
                        # Can't edit in place when looping through the list
                        new_slice_groups = []
                        for group in slice_groups:
                            if axis_size - 1 in group:
                                group.append(axis_size)
                            new_slice_groups.append(group)
                        slice_groups = new_slice_groups

    # Do the conversion in preparation for topup
    run.command('mrconvert ' + se_epi_path + ' topup_in.nii' +
                import_se_epi_manual_pe_table_option +
                ' -strides -1,+2,+3,+4 -export_pe_table topup_datain.txt')
    file.delTemporary(se_epi_path)

    # Run topup
    topup_manual_options = ''
    if app.args.topup_options:
        topup_manual_options = ' ' + app.args.topup_options.strip()
    (topup_stdout, topup_stderr) = run.command(
        topup_cmd +
        ' --imain=topup_in.nii --datain=topup_datain.txt --out=field --fout=field_map' +
        fsl_suffix + ' --config=' + topup_config_path + topup_manual_options)
    with open('topup_output.txt', 'w') as f:
        f.write(topup_stdout + '\n' + topup_stderr)
    if app.verbosity > 2:
        app.console('Output of topup command:\n' + topup_stdout + '\n' + topup_stderr)

    # Apply the warp field to the input image series to get an initial corrected volume estimate
    # applytopup can't receive the complete DWI input and correct it as a whole, because the phase-encoding
    #   details may vary between volumes
    if dwi_manual_pe_scheme:
        run.command(
            'mrconvert ' + dwi_path + import_dwi_pe_table_option +
            ' - | mrinfo - -export_pe_eddy applytopup_config.txt applytopup_indices.txt')
    else:
        run.command('mrinfo ' + dwi_path +
                    ' -export_pe_eddy applytopup_config.txt applytopup_indices.txt')

    # Update: Call applytopup separately for each unique phase-encoding
    # This should be the most compatible option with more complex phase-encoding acquisition designs,
    #   since we don't need to worry about applytopup performing volume recombination
    # Plus, recombination doesn't need to be optimal; we're only using this to derive a brain mask
    applytopup_image_list = []
    index = 1
    with open('applytopup_config.txt', 'r') as f:
        for line in f:
            prefix = os.path.splitext(dwi_path)[0] + '_pe_' + str(index)
            input_path = prefix + '.nii'
            json_path = prefix + '.json'
            temp_path = prefix + '_applytopup.nii'
            output_path = prefix + '_applytopup.mif'
            run.command('dwiextract ' + dwi_path + import_dwi_pe_table_option + ' -pe ' +
                        ','.join(line.split()) + ' - | mrconvert - ' + input_path +
                        ' -json_export ' + json_path)
            run.command(applytopup_cmd + ' --imain=' + input_path +
                        ' --datain=applytopup_config.txt --inindex=' + str(index) +
                        ' --topup=field --out=' + temp_path + ' --method=jac')
            file.delTemporary(input_path)
            temp_path = fsl.findImage(temp_path)
            run.command('mrconvert ' + temp_path + ' ' + output_path + ' -json_import ' +
                        json_path)
            file.delTemporary(json_path)
            file.delTemporary(temp_path)
            applytopup_image_list.append(output_path)
            index += 1

    # Use the initial corrected volumes to derive a brain mask for eddy
    if len(applytopup_image_list) == 1:
        run.command(
            'dwi2mask ' + applytopup_image_list[0] +
            ' - | maskfilter - dilate - | mrconvert - eddy_mask.nii -datatype float32 -strides -1,+2,+3'
        )
    else:
        run.command(
            'mrcat ' + ' '.join(applytopup_image_list) +
            ' - -axis 3 | dwi2mask - - | maskfilter - dilate - | mrconvert - eddy_mask.nii -datatype float32 -strides -1,+2,+3'
        )

    for entry in applytopup_image_list:
        file.delTemporary(entry)

    eddy_in_topup_option = ' --topup=field'

else:

    # Generate a processing mask for eddy based on the uncorrected input DWIs
    run.command(
        'dwi2mask ' + dwi_path +
        ' - | maskfilter - dilate - | mrconvert - eddy_mask.nii -datatype float32 -strides -1,+2,+3'
    )

# Generate the text file containing slice timing / grouping information if necessary
if eddy_mporder:
    if slice_timing:
        # This list contains, for each slice, the timing offset between acquisition of the
        #   first slice in the volume, and acquisition of that slice
        # Eddy however requires a text file where each row contains those slices that were
        #   acquired with a single readout, in ordered rows from first slice (group)
        #   acquired to last slice (group) acquired
        if sum(slice_encoding_direction) < 0:
            slice_timing = reversed(slice_timing)
        slice_groups = [[x[0] for x in g] for _, g in itertools.groupby(
            sorted(enumerate(slice_timing), key=lambda x: x[1]), key=lambda x: x[1])]  #pylint: disable=unused-variable
        app.var(slice_timing, slice_groups)
    # Variable slice_groups may have already been defined in the correct format.
    #   In that instance, there's nothing to do other than write it to file;
    #   UNLESS the slice encoding direction is known to be reversed, in which case
    #   we need to reverse the timings. Would think that this would however be
    #   rare, given it requires that the slspec text file be provided manually but
    #   SliceEncodingDirection to be present.
    elif slice_groups and sum(slice_encoding_direction) < 0:
        new_slice_groups = []
        for group in new_slice_groups:
            new_slice_groups.append([dwi_num_slices - index for index in group])
        app.var(slice_groups, new_slice_groups)
        slice_groups = new_slice_groups

    with open('slspec.txt', 'w') as f:
        for line in slice_groups:
            f.write(' '.join(str(value) for value in line) + '\n')
    eddy_manual_options.append('--slspec=slspec.txt')

# Revert eddy_manual_options from a list back to a single string
eddy_manual_options = (' ' + ' '.join(eddy_manual_options)) if eddy_manual_options else ''

# Prepare input data for eddy
run.command(
    'mrconvert ' + dwi_path + import_dwi_pe_table_option +
    dwi_permute_volumes_pre_eddy_option +
    ' eddy_in.nii -strides -1,+2,+3,+4 -export_grad_fsl bvecs bvals -export_pe_eddy eddy_config.txt eddy_indices.txt'
)
file.delTemporary(dwi_path)

# Run eddy
# If a CUDA version is in PATH, run that first; if it fails, re-try using the non-CUDA version
eddy_all_options = '--imain=eddy_in.nii --mask=eddy_mask.nii --acqp=eddy_config.txt --index=eddy_indices.txt --bvecs=bvecs --bvals=bvals' + eddy_in_topup_option + eddy_manual_options + ' --out=dwi_post_eddy'
eddy_cuda_cmd = fsl.eddyBinary(True)
eddy_openmp_cmd = fsl.eddyBinary(False)
if eddy_cuda_cmd:
    # If running CUDA version, but OpenMP version is also available, don't stop the script if the CUDA version fails
    (eddy_stdout, eddy_stderr) = run.command(eddy_cuda_cmd + ' ' + eddy_all_options,
                                             not eddy_openmp_cmd)
    if app.verbosity > 2:
        app.console('Output of CUDA eddy command:\n' + eddy_stdout + '\n' + eddy_stderr)
    if os.path.isfile('dwi_post_eddy.eddy_parameters'):
        # Flag that the OpenMP version won't be attempted
        eddy_openmp_cmd = ''
    else:
        app.warn('CUDA version of eddy appears to have failed; trying OpenMP version')
if eddy_openmp_cmd:
    (eddy_stdout, eddy_stderr) = run.command(eddy_openmp_cmd + ' ' + eddy_all_options)
    if app.verbosity > 2:
        app.console('Output of OpenMP eddy command:\n' + eddy_stdout + '\n' + eddy_stderr)
file.delTemporary('eddy_in.nii')
file.delTemporary('eddy_mask.nii')
if do_topup:
    file.delTemporary(fsl.findImage('field_fieldcoef'))
with open('eddy_output.txt', 'w') as f:
    f.write(eddy_stdout + '\n' + eddy_stderr)
eddy_output_image_path = fsl.findImage('dwi_post_eddy')

# Get the axis strides from the input series, so the output image can be modified to match
stride_option = ' -strides ' + ','.join([str(i) for i in dwi_header.strides()])

# Check to see whether or not eddy has provided a rotated bvecs file;
#   if it has, import this into the output image
bvecs_path = 'dwi_post_eddy.eddy_rotated_bvecs'
if not os.path.isfile(bvecs_path):
    app.warn(
        'eddy has not provided rotated bvecs file; using original gradient table. Recommend updating FSL eddy to version 5.0.9 or later.'
    )
    bvecs_path = 'bvecs'

# Determine whether or not volume recombination should be performed
# This could be either due to use of -rpe_all option, or just due to the data provided with -rpe_header
# Rather than trying to re-use the code that was used in the case of -rpe_all, run fresh code
# The phase-encoding scheme needs to be checked also
volume_matchings = [dwi_num_volumes] * dwi_num_volumes
volume_pairs = []
app.debug('Commencing gradient direction matching; ' + str(dwi_num_volumes) + ' volumes')
for index1 in range(dwi_num_volumes):
    if volume_matchings[index1] == dwi_num_volumes:  # As yet unpaired
        for index2 in range(index1 + 1, dwi_num_volumes):
            if volume_matchings[index2] == dwi_num_volumes:  # Also as yet unpaired
                # Here, need to check both gradient matching and reversed phase-encode direction
                if not any(dwi_pe_scheme[index1][i] + dwi_pe_scheme[index2][i]
                           for i in range(0, 3)) and grads_match(
                               grad[index1], grad[index2]):
                    volume_matchings[index1] = index2
                    volume_matchings[index2] = index1
                    volume_pairs.append([index1, index2])
                    app.debug('Matched volume ' + str(index1) + ' with ' + str(index2) +
                              '\n' + 'Phase encoding: ' + str(dwi_pe_scheme[index1]) +
                              ' ' + str(dwi_pe_scheme[index2]) + '\n' + 'Gradients: ' +
                              str(grad[index1]) + ' ' + str(grad[index2]))
                    break

if len(volume_pairs) != int(dwi_num_volumes / 2):

    if do_topup:
        file.delTemporary('topup_in.nii')
        file.delTemporary(fsl.findImage('field_map'))

    # Convert the resulting volume to the output image, and re-insert the diffusion encoding
    run.command('mrconvert ' + eddy_output_image_path + ' result.mif' +
                dwi_permute_volumes_post_eddy_option + dwi_post_eddy_crop_option +
                stride_option + ' -fslgrad ' + bvecs_path + ' bvals')
    file.delTemporary(eddy_output_image_path)

else:
    app.console(
        'Detected matching DWI volumes with opposing phase encoding; performing explicit volume recombination'
    )

    # Perform a manual combination of the volumes output by eddy, since LSR is disabled

    # Generate appropriate bvecs / bvals files
    # Particularly if eddy has provided rotated bvecs, since we're combining two volumes into one that
    #   potentially have subject rotation between them (and therefore the sensitisation direction is
    #   not precisely equivalent), the best we can do is take the mean of the two vectors.
    # Manual recombination of volumes needs to take into account the explicit volume matching

    bvecs = [[] for axis in range(3)]
    with open(bvecs_path, 'r') as f:
        for axis, line in enumerate(f):
            bvecs[axis] = line.split()

    bvecs_combined_transpose = []
    bvals_combined = []

    for pair in volume_pairs:
        bvec_sum = [
            float(bvecs[0][pair[0]]) + float(bvecs[0][pair[1]]),
            float(bvecs[1][pair[0]]) + float(bvecs[1][pair[1]]),
            float(bvecs[2][pair[0]]) + float(bvecs[2][pair[1]])
        ]
        norm2 = bvec_sum[0] * bvec_sum[0] + bvec_sum[1] * bvec_sum[1] + bvec_sum[
            2] * bvec_sum[2]
        # If one diffusion sensitisation gradient direction is reversed with respect to
        #   the other, still want to enable their recombination; but need to explicitly
        #   account for this when averaging the two directions
        if norm2 < 0.0:
            bvec_sum = [
                float(bvecs[0][pair[0]]) - float(bvecs[0][pair[1]]),
                float(bvecs[1][pair[0]]) - float(bvecs[1][pair[1]]),
                float(bvecs[2][pair[0]]) - float(bvecs[2][pair[1]])
            ]
            norm2 = bvec_sum[0] * bvec_sum[0] + bvec_sum[1] * bvec_sum[1] + bvec_sum[
                2] * bvec_sum[2]
        # Occasionally a bzero volume can have a zero vector
        if norm2:
            factor = 1.0 / math.sqrt(norm2)
            new_vec = [bvec_sum[0] * factor, bvec_sum[1] * factor, bvec_sum[2] * factor]
        else:
            new_vec = [0.0, 0.0, 0.0]
        bvecs_combined_transpose.append(new_vec)
        bvals_combined.append(0.5 * (grad[pair[0]][3] + grad[pair[1]][3]))

    with open('bvecs_combined', 'w') as f:
        for axis in range(0, 3):
            axis_data = []
            for volume in range(0, int(dwi_num_volumes / 2)):
                axis_data.append(str(bvecs_combined_transpose[volume][axis]))
            f.write(' '.join(axis_data) + '\n')

    with open('bvals_combined', 'w') as f:
        f.write(' '.join([str(b) for b in bvals_combined]))

    # Prior to 5.0.8, a bug resulted in the output field map image from topup having an identity transform,
    #   regardless of the transform of the input image
    # Detect this, and manually replace the transform if necessary
    #   (even if this doesn't cause an issue with the subsequent mrcalc command, it may in the future, it's better for
    #   visualising the script temporary files, and it gives the user a warning about an out-of-date FSL)
    field_map_image = fsl.findImage('field_map')
    field_map_header = image.Header(field_map_image)
    if not image.match('topup_in.nii', field_map_header, 3):
        app.warn(
            'topup output field image has erroneous header; recommend updating FSL to version 5.0.8 or later'
        )
        new_field_map_image = 'field_map_fix.mif'
        run.command('mrtransform ' + field_map_image + ' -replace topup_in.nii ' +
                    new_field_map_image)
        file.delTemporary(field_map_image)
        field_map_image = new_field_map_image
    # In FSL 6.0.0, field map image is erroneously constructed with the same number of volumes as the input image,
    #   with all but the first volume containing intensity-scaled duplicates of the uncorrected input images
    # The first volume is however the expected field offset image
    elif len(field_map_header.size()) == 4:
        app.console('Correcting erroneous FSL 6.0.0 field map image output')
        new_field_map_image = 'field_map_fix.mif'
        run.command('mrconvert ' + field_map_image + ' -coord 3 0 -axes 0,1,2 ' +
                    new_field_map_image)
        file.delTemporary(field_map_image)
        field_map_image = new_field_map_image
    file.delTemporary('topup_in.nii')

    # Derive the weight images
    # Scaling term for field map is identical to the bandwidth provided in the topup config file
    #   (converts Hz to pixel count; that way a simple image gradient can be used to get the Jacobians)
    # Let mrfilter apply the default 1 voxel size gaussian smoothing filter before calculating the field gradient
    #
    #   The jacobian image may be different for any particular volume pair
    #   The appropriate PE directions and total readout times can be acquired from the eddy-style config/index files
    #   eddy_config.txt and eddy_indices.txt

    eddy_config = [[float(f) for f in line.split()]
                   for line in open('eddy_config.txt', 'r').read().split('\n')[:-1]]
    eddy_indices = [int(i) for i in open('eddy_indices.txt', 'r').read().split()]
    app.var(eddy_config, eddy_indices)

    # This section derives, for each phase encoding configuration present, the 'weight' to be applied
    #   to the image during volume recombination, which is based on the Jacobian of the field in the
    #   phase encoding direction
    for index, config in enumerate(eddy_config):
        pe_axis = [i for i, e in enumerate(config[0:3]) if e != 0][0]
        sign_multiplier = ' -1.0 -mult' if config[pe_axis] < 0 else ''
        field_derivative_path = 'field_deriv_pe_' + str(index + 1) + '.mif'
        run.command('mrcalc ' + field_map_image + ' ' + str(config[3]) + ' -mult' +
                    sign_multiplier + ' - | mrfilter - gradient - | mrconvert - ' +
                    field_derivative_path + ' -coord 3 ' + str(pe_axis) + ' -axes 0,1,2')
        jacobian_path = 'jacobian_' + str(index + 1) + '.mif'
        run.command('mrcalc 1.0 ' + field_derivative_path + ' -add 0.0 -max ' +
                    jacobian_path)
        file.delTemporary(field_derivative_path)
        run.command('mrcalc ' + jacobian_path + ' ' + jacobian_path + ' -mult weight' +
                    str(index + 1) + '.mif')
        file.delTemporary(jacobian_path)
    file.delTemporary(field_map_image)

    # If eddy provides its main image output in a compressed format, the code block below will need to
    #   uncompress that image independently for every volume pair. Instead, if this is the case, let's
    #   convert it to an uncompressed format before we do anything with it.
    if eddy_output_image_path.endswith('.gz'):
        new_eddy_output_image_path = 'dwi_post_eddy_uncompressed.mif'
        run.command('mrconvert ' + eddy_output_image_path + ' ' +
                    new_eddy_output_image_path)
        file.delTemporary(eddy_output_image_path)
        eddy_output_image_path = new_eddy_output_image_path

    # If the DWI volumes were permuted prior to running eddy, then the simplest approach is to permute them
    #   back to their original positions; otherwise, the stored gradient vector directions / phase encode
    #   directions / matched volume pairs are no longer appropriate
    if dwi_permute_volumes_post_eddy_option:
        new_eddy_output_image_path = os.path.splitext(
            eddy_output_image_path)[0] + '_volpermuteundo.mif'
        run.command('mrconvert ' + eddy_output_image_path +
                    dwi_permute_volumes_post_eddy_option + ' ' +
                    new_eddy_output_image_path)
        file.delTemporary(eddy_output_image_path)
        eddy_output_image_path = new_eddy_output_image_path

    # This section extracts the two volumes corresponding to each reversed phase-encoded volume pair, and
    #   derives a single image volume based on the recombination equation
    combined_image_list = []
    progress = app.progressBar('Performing explicit volume recombination',
                               len(volume_pairs))
    for index, volumes in enumerate(volume_pairs):
        pe_indices = [eddy_indices[i] for i in volumes]
        run.command('mrconvert ' + eddy_output_image_path + ' volume0.mif -coord 3 ' +
                    str(volumes[0]))
        run.command('mrconvert ' + eddy_output_image_path + ' volume1.mif -coord 3 ' +
                    str(volumes[1]))
        # Volume recombination equation described in Skare and Bammer 2010
        combined_image_path = 'combined' + str(index) + '.mif'
        run.command('mrcalc volume0.mif weight' + str(pe_indices[0]) +
                    '.mif -mult volume1.mif weight' + str(pe_indices[1]) +
                    '.mif -mult -add weight' + str(pe_indices[0]) + '.mif weight' +
                    str(pe_indices[1]) + '.mif -add -divide 0.0 -max ' +
                    combined_image_path)
        combined_image_list.append(combined_image_path)
        run.function(os.remove, 'volume0.mif')
        run.function(os.remove, 'volume1.mif')
        progress.increment()
    progress.done()

    file.delTemporary(eddy_output_image_path)
    for index in range(0, len(eddy_config)):
        file.delTemporary('weight' + str(index + 1) + '.mif')

    # Finally the recombined volumes must be concatenated to produce the resulting image series
    run.command('mrcat ' + ' '.join(combined_image_list) +
                ' - -axis 3 | mrconvert - result.mif' + dwi_post_eddy_crop_option +
                ' -fslgrad bvecs_combined bvals_combined' + stride_option)
    for entry in combined_image_list:
        file.delTemporary(entry)

# Grab any relevant files that eddy has created, and copy them to the requested directory
if eddyqc_path:
    if os.path.exists(eddyqc_path) and not os.path.isdir(eddyqc_path):
        run.function(os.remove, eddyqc_path)
    if not os.path.exists(eddyqc_path):
        run.function(os.makedirs, eddyqc_path)
    for filename in eddyqc_files:
        if os.path.exists('dwi_post_eddy.' + filename):
            run.function(shutil.copy, 'dwi_post_eddy.' + filename,
                         os.path.join(eddyqc_path, filename))

# Build a list of header key-value entries that we want to _remove_ from the
#   output image, as they may have been useful for controlling pre-processing
#   but are no longer required, and will just bloat the key-value listings of
#   all subsequent derived images
# Disabled this for now: The output from eddy is a NIfTI, so all these fields
#   have been lost. For now just neglect to re-introduce them; in the future,
#   this may be combined with GitHub Issue #1188 (proper behaviour of
#   command_history header key-value entry when running a Python script)
#keys_to_remove = [ 'EchoTime', 'FlipAngle', 'MultibandAccelerationFactor', 'PhaseEncodingDirection', 'RepetitionTime', 'SliceEncodingDirection', 'SliceTiming', 'TotalReadoutTime', 'pe_scheme' ]
#clear_property_options = ' ' + ' '.join(['-clear_property '+key for key in keys_to_remove if key in dwi_header.keyval() ])

# Finish!
run.command('mrconvert result.mif ' + path.fromUser(app.args.output, True) +
            grad_export_option + (' -force' if app.forceOverwrite else ''))
app.complete()
