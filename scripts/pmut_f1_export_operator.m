function export = pmut_f1_export_operator(modelPath, manifestPath, outputRoot, maxModelBytes)
%PMUT_F1_EXPORT_OPERATOR 独立的已保存解/算子输入取证导出器；不运行求解。
% 与旧导出器隔离：同次 Eval 导出 p/dom/xyz，模型定义快照不冒充逐 outer 物理真值。
% 可选 resolve_solution_indices=true 通过 mphsolutioninfo 唯一匹配，不猜扫描公式。
% 官方 API: https://doc.comsol.com/6.4/doc/com.comsol.help.comsol/comsol_api_results.52.049.html
% 本地 mli: mphsolutioninfo.m / mphgetproperties.m / mphgetselection.m。
% export = pmut_f1_export_operator(modelPath, manifestPath, outputRoot [, maxModelBytes])
% 默认拒绝大于 8 GiB 的 MPH；outputRoot 必须是新目录。outer/inner 仅是候选索引，
% 每个解都要读回全部参数/频率列核验。观测点表值只作外部参考，不冒充场节点值。
% 从 te2_8_retry_patch 复用 Eval/getData/getImagData 通路，禁止按扫描步长推算索引。
% mphinterp 仅在既有有限元解的精确空间坐标求值（ext=0、指定 outer/inner），
% 用于与 Table9 复压力交叉核对；不做参数空间/频率插值，也不生成新求解真值。

    if nargin < 4
        maxModelBytes = 8 * 1024^3;
    end
    [modelPath, manifestPath, outputRoot, manifest, before, manifestBefore] = ...
        preflight(modelPath, manifestPath, outputRoot, maxModelBytes);
    [ok, message] = mkdir(outputRoot);
    if ~ok
        error('PMUTF1:OutputCreateFailed', 'Cannot create output directory: %s', message);
    end
    export = struct('schema', 'memsharness.pmut_f1_operator_export/v0', ...
        'status', 'running', 'phase', 'hash_start', 'source_model', modelPath, 'source_model_sha256', '', ...
        'source_hash_verification', 'computed_from_file_bytes', ...
        'expected_source_model_sha256', '', 'expected_source_hash_verified', false, ...
        'manifest_path', manifestPath, 'manifest_sha256', '', ...
        'source_before', before, 'source_after', [], 'source_unchanged', false, ...
        'dataset', manifest.dataset, 'field_expression', manifest.field_expression, ...
        'requested', numel(manifest.cases), 'completed', 0, 'cases', {{}}, ...
        'mode_identity', 'unverified', 'training_ready', false, 'release_allowed', false, ...
        'missing_operator_inputs', {{'geometry_topology', 'material_fields', ...
            'boundary_condition_values_and_tags', 'excitation_and_losses'}}, ...
        'point_reference_source', 'scalar_table_reference_not_field_node', ...
        'point_reference_same_model_verified', false, 'error', '');
    try
        % SHA256 来自当前文件实际字节。大小/mtime 同时防止哈希过程中源文件变化。
        write_report(outputRoot, export);
        fprintf('PMUTF1 hash_start source_bytes=%.0f cases=%d\n', before.size_bytes, export.requested);
        export.source_model_sha256 = file_sha256(modelPath);
        if isfield(manifest, 'expected_source_model_sha256')
            export.expected_source_model_sha256 = lower(manifest.expected_source_model_sha256);
            if ~strcmp(export.source_model_sha256, export.expected_source_model_sha256)
                error('PMUTF1:SourceHashMismatch', 'Computed source hash does not match the explicitly expected model hash.');
            end
            export.expected_source_hash_verified = true;
            export.source_hash_verification = 'computed_and_expected_hash_matched';
        end
        export.manifest_sha256 = file_sha256(manifestPath);
        if ~isequal(manifestBefore, file_stamp(manifestPath))
            error('PMUTF1:ManifestChanged', 'Manifest changed between parsing and hashing.');
        end
        assert_source_unchanged(modelPath, before);
        assert_no_lock(modelPath);
        export.phase = 'hash_done';
        write_report(outputRoot, export);
        fprintf('PMUTF1 hash_done source_sha256=%s manifest_sha256=%s\n', ...
            export.source_model_sha256, export.manifest_sha256);

        modelTag = ['PmutF1_' strrep(char(java.util.UUID.randomUUID()), '-', '')];
        export.phase = 'load_start';
        write_report(outputRoot, export);
        fprintf('PMUTF1 load_start\n');
        model = mphload(modelPath, modelTag);
        modelCleanup = onCleanup(@() cleanup_model(modelTag)); %#ok<NASGU>
        export.phase = 'load_done';
        write_report(outputRoot, export);
        fprintf('PMUTF1 load_done\n');
        if ~has_tag(model.result.dataset.tags(), manifest.dataset)
            error('PMUTF1:DatasetMissing', 'Stored-solution dataset is missing: %s', manifest.dataset);
        end
        evalTag = ['f1_' strrep(char(java.util.UUID.randomUUID()), '-', '')];
        numerical = model.result.numerical();
        numerical.create(evalTag, 'Eval');
        node = numerical.get(evalTag);
        node.set('data', manifest.dataset);
        node.set('smooth', 'none');
        node.set('refine', int32(1));
        node.set('recover', 'off');
        node.set('phase', 0);
        node.set('matherr', 'off');
        % 同一保存解的后处理网格并非原始 FE 自由度/完整几何拓扑。
        context = read_definition_context(model);
        contextPath = fullfile(outputRoot, 'model_definition_context.mat');
        atomic_save_new(contextPath, struct('context', context));
        export.model_definition_context = struct('file', contextPath, ...
            'sha256', file_sha256(contextPath), ...
            'outer_binding_verified', false, 'available', context.available);
        fprintf('PMUTF1 context_done available=%d outer_binding_verified=false\n', context.available);
        export.phase = 'resolve_start';
        write_report(outputRoot, export);
        fprintf('PMUTF1 resolve_start\n');
        [selectedCases, resolution] = resolve_indices(model, manifest, outputRoot);
        resolution.source_model = modelPath;
        resolution.source_model_sha256 = export.source_model_sha256;
        resolution.source_hash_verified = true;
        resolution.expected_source_hash_verified = export.expected_source_hash_verified;
        resolution.manifest_sha256 = export.manifest_sha256;
        for k = 1:numel(selectedCases)
            c = selectedCases(k);
            resolution.cases{k}.x_scale = c.x_scale;
            resolution.cases{k}.N_w_te1 = c.N_w_te1;
            resolution.cases{k}.N_w_te2 = c.N_w_te2;
            resolution.cases{k}.frequency_Hz = c.frequency_Hz;
            resolution.cases{k}.source_table_sha256 = c.source_table_sha256;
            resolution.cases{k}.parameter_frequency_readback_verified = false;
            resolution.cases{k}.exact_point_pressure_verified = false;
        end
        % 候选索引先落盘；只有完整 Eval/点值核验成功后才生成最终已核验索引。
        write_json_new(fullfile(outputRoot, 'resolved_index_candidates.json'), resolution);
        options = operator_options(manifest);
        for index = 1:numel(selectedCases)
            selected = selectedCases(index);
            export.phase = 'exporting_case';
            export.active_case_id = selected.case_id;
            write_report(outputRoot, export);
            [rr, ii, domAvailable, domMessage] = read_primary(node, selected);
            xyz_m = rr(1:3, :);
            if ~all(isfinite(xyz_m(:)))
                error('PMUTF1:NonfiniteCoordinates', 'Case %s has nonfinite coordinates.', selected.case_id);
            end
            p_total_Pa = complex(rr(4, :), ii(4, :));
            p_finite_mask = isfinite(real(p_total_Pa)) & isfinite(imag(p_total_Pa));
            if ~any(p_finite_mask)
                error('PMUTF1:NoPressureValues', 'Case %s has no finite pressure values.', selected.case_id);
            end
            pointPressure = verify_point_pressure(model, manifest.dataset, selected);
            dom = rr(5, :);
            mesh = read_evaluation_mesh(node, xyz_m);
            displacement = read_displacement(node, selected, options);
            coefficients = read_coefficients(node, selected, options);
            pointReference = struct('xyz_m', [0, 0, -1e-5], ...
                'p_real_Pa', selected.p_point_real_Pa, 'p_imag_Pa', selected.p_point_imag_Pa, ...
                'source_type', 'scalar_table_reference_not_field_node', ...
                'source_table_sha256', selected.source_table_sha256, ...
                'source_table_row_1based', selected.source_table_row_1based, ...
                'table_hash_verification', 'manifest_declared_not_recomputed', ...
                'pressure_consistent_with_stored_solution', true, ...
                'comparison_rtol', 1e-6, 'comparison_atol_Pa', 1e-9, ...
                'same_source_model_verified', false);
            sample = struct('schema', 'memsharness.pmut_f1_operator_field/v0', ...
                'case_id', selected.case_id, 'xyz_m', xyz_m, ...
                'x_m', xyz_m(1, :), 'y_m', xyz_m(2, :), 'z_m', xyz_m(3, :), ...
                'p_total_Pa', p_total_Pa, 'p_finite_mask', p_finite_mask, ...
                'dom_available', domAvailable, 'dom_message', domMessage, ...
                'dom_alignment', 'same_eval_columns_not_nearest_neighbor', ...
                'evaluation_mesh', mesh, 'displacement', displacement, ...
                'coefficient_fields', {coefficients}, 'case_manifest', selected, ...
                'definition_context_sha256', export.model_definition_context.sha256, ...
                'definition_context_outer_binding_verified', false, ...
                'physics_inputs_complete', false, 'release_allowed', false, ...
                'frequency_Hz', selected.frequency_Hz, 'x_scale', selected.x_scale, ...
                'N_w_te1', selected.N_w_te1, 'N_w_te2', selected.N_w_te2, ...
                'outer_solnum', selected.outer_solnum, 'inner_solnum', selected.inner_solnum, ...
                'solution_identity_verified', true, 'mode_identity', 'unverified', ...
                'solution_identity_verification_scope', 'requested_parameters_frequency_and_point_pressure_not_physics_equivalence', ...
                'source_type', 'simulation', 'source_model', modelPath, ...
                'source_model_sha256', export.source_model_sha256, ...
                'source_hash_verification', export.source_hash_verification, ...
                'expected_source_hash_verified', export.expected_source_hash_verified, ...
                'source_dataset', manifest.dataset, 'canonical_expression', manifest.field_expression, ...
                'manifest_sha256', export.manifest_sha256, 'point_reference', pointReference, ...
                'p_point_stored_solution_Pa', pointPressure, ...
                'point_evaluation_method', 'stored_finite_element_solution_at_exact_coordinate_ext0', ...
                'point_reference_pressure_consistent', true, ...
                'geometry_material_bc_exported', false, 'training_ready', false, ...
                'units', struct('coordinates', 'm', 'pressure', 'Pa', 'frequency', 'Hz'));
            if domAvailable
                sample.dom = dom;
            end
            outputPath = fullfile(outputRoot, [selected.case_id '.mat']);
            atomic_save_new(outputPath, sample);
            export.cases{end + 1} = struct('case_id', selected.case_id, ...
                'file', outputPath, 'sha256', file_sha256(outputPath), ...
                'n_points', size(xyz_m, 2), 'n_finite_pressure', nnz(p_finite_mask), ...
                'point_reference_pressure_consistent', true, ...
                'dom_available', domAvailable, 'evaluation_mesh_available', mesh.available, ...
                'displacement_available', displacement.available, ...
                'physics_inputs_complete', false, 'training_ready', false, ...
                'mode_identity', 'unverified');
            export.completed = index;
            resolution.cases{index}.parameter_frequency_readback_verified = true;
            resolution.cases{index}.exact_point_pressure_verified = true;
            export.phase = 'case_done';
            write_report(outputRoot, export);
            fprintf('PMUTF1 case_done %d/%d case_id=%s n_points=%d\n', ...
                export.completed, export.requested, selected.case_id, size(xyz_m, 2));
        end
        export.source_after = file_stamp(modelPath);
        assert_source_unchanged(modelPath, before);
        assert_no_lock(modelPath);
        export.source_unchanged = true;
        write_json_new(fullfile(outputRoot, 'resolved_index.json'), resolution);
        export.resolved_index_sha256 = file_sha256(fullfile(outputRoot, 'resolved_index.json'));
        export.status = 'complete';
        export.phase = 'final';
        write_report(outputRoot, export);
        fprintf('PMUTF1 final status=complete cases=%d/%d training_ready=false\n', export.completed, export.requested);
    catch err
        export.status = 'failed';
        export.failed_phase = export.phase;
        export.phase = 'final';
        export.error = struct('identifier', err.identifier, 'message', err.message);
        try
            export.source_after = file_stamp(modelPath);
            export.source_unchanged = isequal(before, export.source_after);
        catch
            export.source_unchanged = false;
        end
        write_report(outputRoot, export);
        fprintf(2, 'PMUTF1 final status=failed phase=%s identifier=%s cases=%d/%d\n', ...
            export.failed_phase, err.identifier, export.completed, export.requested);
        rethrow(err);
    end
end

function [modelPath, manifestPath, outputRoot, manifest, before, manifestBefore] = preflight(modelPath, manifestPath, outputRoot, maximum)
    if ~isnumeric(maximum) || ~isscalar(maximum) || ~isreal(maximum) || ~isfinite(maximum) || maximum <= 0
        error('PMUTF1:InvalidSizeLimit', 'maxModelBytes must be a positive finite number.');
    end
    modelPath = canonical_path(modelPath);
    manifestPath = canonical_path(manifestPath);
    outputRoot = canonical_path(outputRoot);
    [~, ~, extension] = fileparts(modelPath);
    if ~isfile(modelPath) || ~strcmpi(extension, '.mph')
        error('PMUTF1:SourceMissing', 'An existing .mph source file is required: %s', modelPath);
    end
    assert_no_lock(modelPath);
    before = file_stamp(modelPath);
    if before.size_bytes == 0 || before.size_bytes > maximum
        error('PMUTF1:ModelSizeLimit', 'MPH size %.0f exceeds the allowed range (1..%.0f bytes).', before.size_bytes, maximum);
    end
    if exist(outputRoot, 'file') || isfolder(outputRoot)
        error('PMUTF1:OutputExists', 'Output must be a new directory: %s', outputRoot);
    end
    if ~isfolder(fileparts(outputRoot))
        error('PMUTF1:OutputParentMissing', 'Output parent directory must already exist.');
    end
    if ~isfile(manifestPath)
        error('PMUTF1:ManifestMissing', 'Manifest is missing: %s', manifestPath);
    end
    manifestBefore = file_stamp(manifestPath);
    manifest = jsondecode(fileread(manifestPath));
    validate_manifest(manifest);
end

function validate_manifest(manifest)
    required = {'schema', 'dataset', 'field_expression', 'observation_xyz_m', 'cases'};
    if ~isstruct(manifest) || ~isscalar(manifest) || ~all(isfield(manifest, required))
        error('PMUTF1:InvalidManifest', 'Manifest fields are missing.');
    end
    if ~any(strcmp(manifest.schema, {'memsharness.pmut_f1_export_manifest/v0', ...
            'memsharness.pmut_f1_operator_export_manifest/v0'})) || ...
            ~ischar(manifest.dataset) || isempty(regexp(manifest.dataset, '^[A-Za-z][A-Za-z0-9_]*$', 'once')) || ...
            ~strcmp(manifest.field_expression, 'acpr.p_t')
        error('PMUTF1:InvalidManifest', 'Manifest schema/dataset/field expression is not supported.');
    end
    if ~isnumeric(manifest.observation_xyz_m) || ...
            ~isequal(reshape(manifest.observation_xyz_m, 1, []), [0, 0, -1e-5])
        error('PMUTF1:InvalidManifest', 'Observation must be model-global (0,0,-10 um).');
    end
    if ~isstruct(manifest.cases) || isempty(manifest.cases)
        error('PMUTF1:InvalidManifest', 'At least one case is required.');
    end
    if isfield(manifest, 'expected_source_model_sha256') && ...
            (~ischar(manifest.expected_source_model_sha256) || ...
             isempty(regexp(manifest.expected_source_model_sha256, '^[a-fA-F0-9]{64}$', 'once')))
        error('PMUTF1:InvalidManifest', 'Expected source model hash must be 64 hexadecimal characters when supplied.');
    end
    fields = {'case_id', 'x_scale', 'N_w_te1', 'N_w_te2', 'frequency_Hz', ...
        'outer_solnum', 'inner_solnum', 'p_point_real_Pa', 'p_point_imag_Pa', ...
        'source_table_sha256', 'source_table_row_1based', 'mode_identity'};
    if ~all(isfield(manifest.cases, fields))
        error('PMUTF1:InvalidManifest', 'A case is missing required fields.');
    end
    ids = cell(1, numel(manifest.cases));
    resolve = false;
    if isfield(manifest, 'resolve_solution_indices')
        if ~islogical(manifest.resolve_solution_indices) || ~isscalar(manifest.resolve_solution_indices)
            error('PMUTF1:InvalidManifest', 'resolve_solution_indices must be a JSON boolean.');
        end
        resolve = manifest.resolve_solution_indices;
    end
    operator_options(manifest);
    numericFields = {'x_scale', 'N_w_te1', 'N_w_te2', 'frequency_Hz', ...
        'p_point_real_Pa', 'p_point_imag_Pa', 'source_table_row_1based'};
    integerFields = {'N_w_te1', 'N_w_te2', 'source_table_row_1based'};
    for index = 1:numel(manifest.cases)
        selected = manifest.cases(index);
        if ~ischar(selected.case_id) || isempty(regexp(selected.case_id, '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$', 'once'))
            error('PMUTF1:InvalidManifest', 'case_id must be a safe, unique filename stem.');
        end
        ids{index} = selected.case_id;
        for key = {'outer_solnum', 'inner_solnum'}
            value = selected.(key{1});
            if resolve && isempty(value)
                continue;
            end
            if ~isnumeric(value) || ~isscalar(value) || ~isreal(value) || ...
                    ~isfinite(value) || value < 1 || fix(value) ~= value || value > intmax('int32')
                error('PMUTF1:InvalidManifest', 'Missing/invalid indices require explicit runtime resolution.');
            end
        end
        for k = 1:numel(numericFields)
            value = selected.(numericFields{k});
            if ~isnumeric(value) || ~isscalar(value) || ~isreal(value) || ~isfinite(value)
                error('PMUTF1:InvalidManifest', 'Case %s: %s must be a finite real scalar.', selected.case_id, numericFields{k});
            end
        end
        for k = 1:numel(integerFields)
            value = selected.(integerFields{k});
            if value < 1 || fix(value) ~= value || value > intmax('int32')
                error('PMUTF1:InvalidManifest', 'Case %s: %s must be a positive int32.', selected.case_id, integerFields{k});
            end
        end
        if selected.x_scale < 0.2 || selected.x_scale > 1 || ...
                ~any(selected.N_w_te2 == 5:9) || selected.N_w_te1 >= selected.N_w_te2 || selected.frequency_Hz <= 0
            error('PMUTF1:InvalidManifest', 'Case %s is outside the frozen design domain.', selected.case_id);
        end
        if ~ischar(selected.source_table_sha256) || ...
                isempty(regexp(selected.source_table_sha256, '^[a-fA-F0-9]{64}$', 'once')) || ...
                ~strcmp(selected.mode_identity, 'unverified')
            error('PMUTF1:InvalidManifest', 'Case table hash or unverified mode status is invalid.');
        end
    end
    if numel(unique(lower(string(ids)))) ~= numel(ids)
        error('PMUTF1:InvalidManifest', 'Duplicate case IDs are not allowed (case insensitive).');
    end
end

function [rr, ii] = eval_one(node, outer, inner, count)
    node.set('outersolnum', int32(outer));
    node.set('solnum', int32(inner));
    % outersolnum 使用已有现场脚本验证过的读回 API；inner 身份由实际 freq 全列核验。
    if double(node.getInt('outersolnum')) ~= outer
        error('PMUTF1:IndexReadbackMismatch', 'Stored-solution index readback differs from the request.');
    end
    rr = normalize_eval(double(node.getData()), count);
    if logical(node.isComplex())
        ii = normalize_eval(double(node.getImagData()), count);
    else
        ii = zeros(size(rr));
    end
    if ~isequal(size(rr), size(ii))
        error('PMUTF1:EvaluationShape', 'Real/imaginary shapes differ.');
    end
end

function data = normalize_eval(raw, count)
    data = squeeze(raw);
    if isempty(data) || ndims(data) > 2
        error('PMUTF1:EvaluationShape', 'Expected one stored solution, received shape %s.', mat2str(size(raw)));
    end
    if size(data, 1) ~= count && size(data, 2) == count
        data = data.';
    end
    if size(data, 1) ~= count
        error('PMUTF1:EvaluationShape', 'Expected %d expression rows, received shape %s.', count, mat2str(size(raw)));
    end
end

function validate_solution_columns(rr, ii, selected)
    expected = [selected.frequency_Hz, selected.x_scale, selected.N_w_te1, selected.N_w_te2];
    tolerance = [1, 5e-9, 5e-9, 5e-9];
    for index = 1:4
        values = rr(index + 5, :);
        imaginary = ii(index + 5, :);
        if isempty(values) || any(~isfinite(values)) || any(abs(values - expected(index)) > tolerance(index)) || ...
                any(~isfinite(imaginary)) || any(abs(imaginary) > 1e-12)
            error('PMUTF1:SolutionIdentityMismatch', 'Case %s: stored parameter/frequency column %d differs.', selected.case_id, index);
        end
    end
end

function pressure = verify_point_pressure(model, dataset, selected)
    % COMSOL 6.4 mli/mphinterp.m：coord 指定空间位置，solnum/outer 固定已存解，
    % ext=0 禁止越界外推；此处不会跨参数、跨频率或选最近网格节点代替目标点。
    pressure = mphinterp(model, 'acpr.p_t', 'coord', [0; 0; -1e-5], ...
        'dataset', dataset, 'outersolnum', selected.outer_solnum, ...
        'solnum', selected.inner_solnum, 'complexout', 'on', ...
        'ext', 0, 'coorderr', 'on', 'matherr', 'on');
    if ~isnumeric(pressure) || ~isscalar(pressure) || ...
            ~isfinite(real(pressure)) || ~isfinite(imag(pressure))
        error('PMUTF1:InvalidPointValue', 'Case %s: exact-coordinate pressure must be one finite complex value.', selected.case_id);
    end
    reference = complex(selected.p_point_real_Pa, selected.p_point_imag_Pa);
    tolerance = 1e-9 + 1e-6 * abs(reference);
    if abs(pressure - reference) > tolerance
        error('PMUTF1:PointPressureMismatch', ...
            'Case %s: stored point pressure and scalar-table reference differ (|delta|=%g Pa, tolerance=%g Pa).', ...
            selected.case_id, abs(pressure - reference), tolerance);
    end
end


function expressions = core_expressions()
    expressions = {'x', 'y', 'z', 'acpr.p_t', 'dom', 'freq', 'x_scale', 'N_w_te1', 'N_w_te2'};
end

function [rr, ii, available, message] = read_primary(node, selected)
    available = false;
    message = '';
    try
        node.set('expr', core_expressions());
        node.set('unit', {'m', 'm', 'm', 'Pa', '1', 'Hz', '1', '1', '1'});
        [rr, ii] = eval_one(node, selected.outer_solnum, selected.inner_solnum, 9);
        validate_solution_columns(rr, ii, selected);
        dom = rr(5, :);
        pressureMask = isfinite(rr(4, :)) & isfinite(ii(4, :));
        if ~any(pressureMask) || any(~isfinite(dom(pressureMask))) || ...
                any(dom(pressureMask) < 1 | dom(pressureMask) ~= fix(dom(pressureMask))) || ...
                any(~isfinite(ii(5, pressureMask)) | ii(5, pressureMask) ~= 0)
            error('PMUTF1:InvalidDomainIds', 'Domain IDs must be finite positive integers on every valid pressure sample.');
        end
        available = true;
    catch err
        rethrow_identity_error(err);
        message = [err.identifier ': ' err.message];
        % 域求值失败时仅回收声压，绝不将另一次 Eval 的 dom 对齐或补齐。
        expr = core_expressions();
        node.set('expr', expr([1:4, 6:9]));
        node.set('unit', {'m', 'm', 'm', 'Pa', 'Hz', '1', '1', '1'});
        [rr, ii] = eval_one(node, selected.outer_solnum, selected.inner_solnum, 8);
        rr = [rr(1:4, :); NaN(1, size(rr, 2)); rr(5:8, :)];
        ii = [ii(1:4, :); NaN(1, size(ii, 2)); ii(5:8, :)];
        validate_solution_columns(rr, ii, selected);
    end
end

function rethrow_identity_error(err)
    if any(strcmp(err.identifier, {'PMUTF1:SolutionIdentityMismatch', 'PMUTF1:IndexReadbackMismatch'}))
        rethrow(err);
    end
end

function mesh = read_evaluation_mesh(node, xyz)
    mesh = struct('available', false, 'source', 'same_eval_saved_solution_evaluation_mesh', ...
        'original_fe_mesh_verified', false, 'geometry_topology_verified', false, ...
        'connectivity_index_base', 'comsol_api_native_not_normalized', 'error', '');
    try
        coords = double(node.getCoordinates());
        if ~isequal(coords, xyz)
            error('PMUTF1:MeshCoordinatesMismatch', 'Eval coordinates differ from x/y/z expression columns.');
        end
        elements = double(node.getElements());
        if isempty(elements) || any(~isfinite(elements(:))) || any(elements(:) < 0) || ...
                any(elements(:) ~= fix(elements(:))) || any(elements(:) > size(xyz, 2))
            error('PMUTF1:InvalidEvaluationMesh', 'Invalid raw Eval connectivity.');
        end
        mesh.xyz_m = coords;
        mesh.elements_native = elements;
        mesh.available = true;
        try
            mesh.vertex_elements_native = double(node.getVertexElements());
        catch err
            mesh.vertex_elements_error = [err.identifier ': ' err.message];
        end
    catch err
        mesh.error = [err.identifier ': ' err.message];
    end
end

function options = operator_options(manifest)
    options = struct('displacement', [], 'coefficients', []);
    if ~isfield(manifest, 'operator_exports')
        return;
    end
    supplied = manifest.operator_exports;
    if ~isstruct(supplied) || ~isscalar(supplied)
        error('PMUTF1:InvalidManifest', 'operator_exports must be an object.');
    end
    if isfield(supplied, 'displacement') && ~isempty(supplied.displacement)
        d = supplied.displacement;
        if ~isstruct(d) || ~isscalar(d) || ~all(isfield(d, {'expressions', 'units', 'source_note'}))
            error('PMUTF1:InvalidManifest', 'Displacement needs expressions, units and audited source_note.');
        end
        expressions = as_text_list(d.expressions);
        units = as_text_list(d.units);
        if numel(expressions) ~= 3 || numel(units) ~= 3 || ~all(strcmp(units, 'm'))
            error('PMUTF1:InvalidManifest', 'Displacement must declare three expressions in meters.');
        end
        validate_probe_text(expressions);
        require_note(d.source_note);
        d.expressions = expressions;
        d.units = units;
        options.displacement = d;
    end
    if isfield(supplied, 'coefficients') && ~isempty(supplied.coefficients)
        c = supplied.coefficients;
        if ~isstruct(c) || ~all(isfield(c, {'name', 'expression', 'unit', 'semantic_role', 'source_note'})) || numel(c) > 64
            error('PMUTF1:InvalidManifest', 'At most 64 declared coefficient probes are supported.');
        end
        names = cell(1, numel(c));
        for k = 1:numel(c)
            names{k} = c(k).name;
            if ~ischar(c(k).name) || isempty(regexp(c(k).name, '^[A-Za-z][A-Za-z0-9_]{0,63}$', 'once'))
                error('PMUTF1:InvalidManifest', 'Coefficient name must be a safe identifier.');
            end
            validate_probe_text({c(k).expression});
            require_note(c(k).unit);
            require_note(c(k).semantic_role);
            require_note(c(k).source_note);
        end
        if numel(unique(names)) ~= numel(names)
            error('PMUTF1:InvalidManifest', 'Duplicate coefficient names.');
        end
        options.coefficients = c;
    end
end

function require_note(value)
    if ~ischar(value) || isempty(strtrim(value)) || numel(value) > 2000
        error('PMUTF1:InvalidManifest', 'Probe metadata must be nonempty text.');
    end
end

function validate_probe_text(values)
    for k = 1:numel(values)
        value = values{k};
        % 只允许读变量标识，不执行任意用户表达式/Java/MATLAB代码。
        if ~ischar(value) || isempty(regexp(value, '^[A-Za-z][A-Za-z0-9_.]*$', 'once')) || numel(value) > 160
            error('PMUTF1:InvalidManifest', 'Probes must be declared COMSOL variable identifiers, not executable expressions.');
        end
    end
end

function output = read_displacement(node, selected, options)
    output = struct('available', false, 'status', 'not_requested', ...
        'role', 'forced_response_displacement_not_eigenmode', 'mode_identity', 'unverified');
    if isempty(options.displacement)
        return;
    end
    spec = options.displacement;
    output = read_optional_block(node, selected, spec.expressions, spec.units);
    output.role = 'forced_response_displacement_not_eigenmode';
    output.mode_identity = 'unverified';
    output.source_note = spec.source_note;
end

function output = read_coefficients(node, selected, options)
    output = cell(1, numel(options.coefficients));
    for k = 1:numel(options.coefficients)
        spec = options.coefficients(k);
        block = read_optional_block(node, selected, {spec.expression}, {spec.unit});
        block.name = spec.name;
        block.semantic_role = spec.semantic_role;
        block.source_note = spec.source_note;
        block.material_or_bc_binding_verified = false;
        output{k} = block;
    end
end

function output = read_optional_block(node, selected, expressions, units)
    output = struct('available', false, 'status', 'unavailable', ...
        'expressions', {expressions}, 'units', {units}, ...
        'source', 'selected_saved_solution_eval', 'physical_semantics_verified', false, 'error', '');
    try
        expr = [core_expressions(), expressions];
        node.set('expr', expr);
        % 单位按声明显式转换；不将默认单位数值贴上 SI 标签。
        node.set('unit', [{'m', 'm', 'm', 'Pa', '1', 'Hz', '1', '1', '1'}, units]);
        [rr, ii] = eval_one(node, selected.outer_solnum, selected.inner_solnum, numel(expr));
        validate_solution_columns(rr, ii, selected);
        xyz = rr(1:3, :);
        values = complex(rr(10:end, :), ii(10:end, :));
        mask = all(isfinite(real(values)) & isfinite(imag(values)), 1);
        if any(~isfinite(xyz(:))) || ~any(mask)
            error('PMUTF1:OptionalFieldUnavailable', 'No finite optional field values at finite coordinates.');
        end
        dom = rr(5, :);
        domMask = isfinite(dom) & dom >= 1 & dom == fix(dom) & isfinite(ii(5, :)) & ii(5, :) == 0;
        output.xyz_m = xyz;
        output.values = values;
        output.finite_mask = mask;
        output.dom_available = all(domMask(mask));
        if output.dom_available
            output.dom = dom;
        end
        output.evaluation_mesh = read_evaluation_mesh(node, xyz);
        output.available = true;
        output.status = 'evaluated_not_physics_certified';
        output.coordinate_alignment = 'own_eval_columns_not_assumed_pressure_node_alignment';
    catch err
        rethrow_identity_error(err);
        output.error = [err.identifier ': ' err.message];
    end
end

function [selectedCases, resolution] = resolve_indices(model, manifest, outputRoot)
    selectedCases = manifest.cases;
    resolution = struct('schema', 'memsharness.pmut_f1_resolved_indices/v0', ...
        'dataset', manifest.dataset, 'method', 'manifest_indices_verified_later_by_eval', ...
        'cases', {{}}, 'training_ready', false);
    if ~isfield(manifest, 'resolve_solution_indices') || ~manifest.resolve_solution_indices
        for k = 1:numel(selectedCases)
            resolution.cases{end + 1} = struct('case_id', selectedCases(k).case_id, ...
                'inner_solnum', selectedCases(k).inner_solnum, 'outer_solnum', selectedCases(k).outer_solnum);
        end
        return;
    end
    info = mphsolutioninfo(model, 'dataset', manifest.dataset, 'cellmap', 'on');
    % part.dataset 对聚合解和内部 ParametricStore 都可能相同，不能据此选解。
    % 直接读 Solution 数据集的实际绑定；缺失时保存证据后拒绝，不猜 sol2。
    binding = struct('dataset', manifest.dataset, 'type', '', 'solution_tag', '', ...
        'readback_available', false, 'api', 'dataset_getType_getString_solution', 'error', '');
    try
        datasetNode = model.result.dataset.get(manifest.dataset);
        binding.type = char(datasetNode.getType());
        binding.solution_tag = char(datasetNode.getString('solution'));
        binding.readback_available = strcmp(binding.type, 'Solution') && ...
            ~isempty(regexp(binding.solution_tag, '^[A-Za-z][A-Za-z0-9_]*$', 'once'));
    catch err
        binding.error = [err.identifier ': ' err.message];
    end
    % 原始 map、headers、solution tag 与 dataset 在匹配之前独立保存；失败仍可诊断。
    rawPath = fullfile(outputRoot, 'solution_map_raw.mat');
    atomic_save_new(rawPath, struct('schema', 'memsharness.pmut_f1_solution_map_evidence/v0', ...
        'dataset', manifest.dataset, 'api', 'mphsolutioninfo_dataset_cellmap_on', ...
        'solution_info', info, 'dataset_binding', binding, 'solution_identity_verified', false));
    resolution.raw_solution_map = struct('file', rawPath, 'sha256', file_sha256(rawPath));
    fprintf('PMUTF1 resolve_map_saved\n');
    resolution.dataset_binding = binding;
    if ~binding.readback_available || ~isfield(info, binding.solution_tag)
        error('PMUTF1:DatasetBindingUnavailable', 'An explicitly bound Solution dataset and its map are required; refusing inferred binding.');
    end
    solutionTag = binding.solution_tag;
    part = info.(solutionTag);
    if ~isstruct(part) || ~isscalar(part) || ~all(isfield(part, {'map', 'mapheaders', 'dataset'})) || ...
            ~any(strcmp(as_text_list(part.dataset), manifest.dataset))
        error('PMUTF1:InvalidSolutionMap', 'Bound solution does not supply a map for the requested dataset.');
    end
    headers = as_text_list(part.mapheaders);
    values = part.map;
    if ~isnumeric(values) || ~isreal(values) || isempty(values) || ...
            size(values, 2) ~= numel(headers) || numel(headers) < 5
        error('PMUTF1:InvalidSolutionMap', 'Unsupported map layout for %s.', solutionTag);
    end
    names = lower(regexprep(string(headers), '[ _-]', ''));
    inner = find(ismember(names, ["inner", "innersolnum", "solnum", "innersolutionnumber"]));
    outer = find(ismember(names, ["outer", "outersolnum", "outersolutionnumber"]));
    if numel(inner) ~= 1 || numel(outer) ~= 1 || inner ~= numel(headers) - 1 || outer ~= numel(headers)
        error('PMUTF1:InvalidSolutionMap', 'Map must explicitly identify final inner/outer columns.');
    end
    [parameterColumns, metadata] = map_parameter_columns(part, headers, values, inner);
    resolution.parameter_column_evidence = metadata;
    resolution.method = 'mphsolutioninfo_unique_parameter_frequency_row_then_eval_and_exact_point_verification';
    for k = 1:numel(selectedCases)
        selected = selectedCases(k);
        matches = {};
        wanted = {'x_scale', 'N_w_te1', 'freq'};
        expected = [selected.x_scale, selected.N_w_te1, selected.frequency_Hz];
        tolerance = [5e-9, 0, 1];
        hit = true(size(values, 1), 1);
        for j = 1:3
            col = parameterColumns(strcmp(headers(parameterColumns), wanted{j}));
            if numel(col) ~= 1
                error('PMUTF1:InvalidSolutionMap', 'Map needs one exact %s header.', wanted{j});
            end
            hit = hit & isfinite(values(:, col)) & abs(values(:, col) - expected(j)) <= tolerance(j);
        end
        n2 = parameterColumns(strcmp(headers(parameterColumns), 'N_w_te2'));
        if numel(n2) > 1
            error('PMUTF1:InvalidSolutionMap', 'Ambiguous N_w_te2 header.');
        elseif ~isempty(n2)
            hit = hit & isfinite(values(:, n2)) & values(:, n2) == selected.N_w_te2;
        end
        rows = find(hit);
        for row = reshape(rows, 1, [])
            actual = values(row, [inner, outer]);
            if any(~isfinite(actual) | actual < 1 | actual ~= fix(actual) | actual > intmax('int32'))
                error('PMUTF1:InvalidSolutionMap', 'Invalid resolved solution indices.');
            end
            matches{end + 1} = struct('case_id', selected.case_id, 'solution_tag', solutionTag, ...
                'mapheaders', {headers}, 'matched_row_1based', row, ...
                'matched_values', values(row, :), 'inner_solnum', actual(1), ...
                'outer_solnum', actual(2), 'N_w_te2_in_map', ~isempty(n2)); %#ok<AGROW>
        end
        if numel(matches) ~= 1
            error('PMUTF1:SolutionMapNotUnique', 'Case %s matched %d map rows; refusing guessed indices.', selected.case_id, numel(matches));
        end
        match = matches{1};
        for key = {'inner_solnum', 'outer_solnum'}
            prior = selected.(key{1});
            if ~isempty(prior) && prior ~= match.(key{1})
                error('PMUTF1:IndexReadbackMismatch', 'Declared and runtime-resolved indices differ.');
            end
            selectedCases(k).(key{1}) = match.(key{1});
        end
        resolution.cases{end + 1} = match;
    end
end

function [columns, evidence] = map_parameter_columns(part, headers, values, inner)
    columns = 1:(inner - 1);
    evidence = struct('method', 'unique_parameter_headers', 'parameter_columns_1based', columns, ...
        'excluded_metadata_columns_1based', [], 'excluded_metadata_names', {{}}, ...
        'excluded_metadata_values', [], 'not_current_model_parameter_values', true);
    if numel(unique(headers(columns))) == numel(columns)
        return;
    end
    % 实测 mphsolutioninfo 的 parameters 尾部包含 paramsweepnames/vals 快照。
    % 仅在名字、数量、parameters 对齐且每整列恒等于该元数据时排除该块。
    % 不是选择重复列的 first/last，也绝不读取当前 model.param 来替代扫描值。
    if ~all(isfield(part, {'parameters', 'paramsweepnames', 'paramsweepvals'}))
        error('PMUTF1:InvalidSolutionMap', 'Repeated parameter headers lack explicit sweep metadata.');
    end
    parameters = as_text_list(part.parameters);
    sweepNames = as_text_list(part.paramsweepnames);
    sweepValues = part.paramsweepvals;
    count = numel(sweepNames);
    if ~isequal(parameters, headers(columns)) || count < 1 || count >= numel(columns) || ...
            ~isnumeric(sweepValues) || ~isreal(sweepValues) || numel(sweepValues) ~= count || ...
            any(~isfinite(sweepValues(:))) || numel(unique(sweepNames)) ~= count
        error('PMUTF1:InvalidSolutionMap', 'Invalid repeated-header sweep metadata.');
    end
    metadataColumns = columns(end - count + 1:end);
    sweepValues = reshape(sweepValues, 1, []);
    if ~isequal(headers(metadataColumns), sweepNames)
        error('PMUTF1:InvalidSolutionMap', 'Sweep metadata names do not exactly identify the appended block.');
    end
    for j = 1:count
        if any(~isfinite(values(:, metadataColumns(j)))) || ...
                any(values(:, metadataColumns(j)) ~= sweepValues(j))
            error('PMUTF1:InvalidSolutionMap', 'Sweep metadata columns are not constant at the declared values.');
        end
    end
    columns = columns(1:end - count);
    if numel(unique(headers(columns))) ~= numel(columns) || ...
            ~all(ismember(sweepNames, headers(columns)))
        error('PMUTF1:InvalidSolutionMap', 'Actual parameter columns remain ambiguous or are absent.');
    end
    evidence.method = 'explicit_paramsweep_metadata_names_values_and_all_rows_verified';
    evidence.parameter_columns_1based = columns;
    evidence.excluded_metadata_columns_1based = metadataColumns;
    evidence.excluded_metadata_names = sweepNames;
    evidence.excluded_metadata_values = sweepValues;
end

function context = read_definition_context(model)
    % getter 读取的是载入时模型定义，不能自动绑定到每个历史 outer。
    context = struct('schema', 'memsharness.pmut_operator_definition_context/v0', ...
        'scope', 'loaded_model_definition_snapshot_not_per_outer_state', ...
        'outer_binding_verified', false, 'available', false, 'errors', {{}}, 'components', {{}});
    try
        context.global_parameter_expressions = mphgetexpressions(model.param());
    catch err
        context.errors{end + 1} = ['parameters: ' err.identifier ': ' err.message];
    end
    % 仅载入态定义快照（可与保存 outer 的历史状态不同），不执行任何 feature。
    for group = {'func', 'study'}
        name = group{1};
        try
            list = javaMethod(name, model);
            tags = as_text_list(list.tags());
            nodes = cell(1, numel(tags));
            for k = 1:numel(tags)
                nodes{k} = definition_node(javaMethod(name, model, tags{k}), 0);
            end
            context.(name) = nodes;
        catch err
            context.errors{end + 1} = [name ': ' err.identifier ': ' err.message];
        end
    end
    try
        components = model.component();
        tags = as_text_list(components.tags());
        for k = 1:numel(tags)
            component = model.component(tags{k});
            entry = struct('tag', tags{k}, 'outer_binding_verified', false);
            for group = {'material', 'physics', 'multiphysics', 'variable', 'geom'}
                name = group{1};
                try
                    list = javaMethod(name, component);
                    childTags = as_text_list(list.tags());
                    nodes = cell(1, numel(childTags));
                    for j = 1:numel(childTags)
                        node = javaMethod(name, component, childTags{j});
                        nodes{j} = definition_node(node, 0);
                    end
                    entry.(name) = nodes;
                catch err
                    entry.([name '_error']) = [err.identifier ': ' err.message];
                end
            end
            context.components{end + 1} = entry;
        end
        context.available = ~isempty(context.components);
    catch err
        context.errors{end + 1} = ['components: ' err.identifier ': ' err.message];
    end
end

function item = definition_node(node, depth)
    item = struct('outer_binding_verified', false, 'errors', {{}}, 'truncated', false);
    try; item.tag = char(node.tag()); catch err; item.errors{end + 1} = ['tag: ' err.message]; end
    try; item.label = char(node.label()); catch err; item.errors{end + 1} = ['label: ' err.message]; end
    try; item.type = char(node.getType()); catch err; item.errors{end + 1} = ['type: ' err.message]; end
    try; item.active = logical(node.isActive()); catch err; item.errors{end + 1} = ['active: ' err.message]; end
    try; item.properties = mphgetproperties(node, 'returnstring', 'on');
    catch err; item.errors{end + 1} = ['properties: ' err.message]; end
    try; item.expressions = mphgetexpressions(node);
    catch err; item.errors{end + 1} = ['expressions: ' err.message]; end
    try; item.selection = mphgetselection(node.selection());
    catch err; item.errors{end + 1} = ['selection: ' err.message]; end
    if depth >= 8
        item.truncated = true;
        return;
    end
    for group = {'feature', 'propertyGroup', 'func'}
        name = group{1};
        try
            list = javaMethod(name, node);
            tags = as_text_list(list.tags());
            children = cell(1, min(numel(tags), 500));
            if numel(tags) > 500
                item.truncated = true;
            end
            for k = 1:numel(children)
                child = javaMethod(name, node, tags{k});
                children{k} = definition_node(child, depth + 1);
            end
            item.(name) = children;
        catch err
            item.errors{end + 1} = [name ': ' err.identifier ': ' err.message];
        end
    end
end

function values = as_text_list(raw)
    if ischar(raw)
        values = {raw};
    elseif iscell(raw)
        values = cellfun(@char, reshape(raw, 1, []), 'UniformOutput', false);
    else
        values = cell(1, numel(raw));
        for k = 1:numel(raw)
            values{k} = char(raw(k));
        end
    end
end

function write_json_new(path, payload)
    if exist(path, 'file')
        error('PMUTF1:OutputExists', 'Refusing to overwrite evidence: %s', path);
    end
    fid = fopen(path, 'w', 'n', 'UTF-8');
    if fid < 0
        error('PMUTF1:ReportWriteFailed', 'Cannot write index evidence.');
    end
    closer = onCleanup(@() fclose(fid)); %#ok<NASGU>
    fprintf(fid, '%s\n', jsonencode(payload));
end

function path = canonical_path(path)
    if ~(ischar(path) || (isstring(path) && isscalar(path))) || strlength(string(path)) == 0
        error('PMUTF1:InvalidPath', 'Paths must be nonempty text scalars.');
    end
    path = char(java.io.File(char(path)).getCanonicalPath());
end

function stamp = file_stamp(path)
    file = java.io.File(path);
    if ~file.isFile()
        error('PMUTF1:SourceMissing', 'Source file is no longer available: %s', path);
    end
    stamp = struct('size_bytes', double(file.length()), 'mtime_millis', double(file.lastModified()));
end

function assert_source_unchanged(path, before)
    if ~isequal(before, file_stamp(path))
        error('PMUTF1:SourceChanged', 'Source MPH size or mtime changed; exported artifacts are rejected.');
    end
end

function assert_no_lock(path)
    [parent, stem, ~] = fileparts(path);
    locks = {[path '.lock'], fullfile(parent, [stem '.lock'])};
    for k = 1:numel(locks)
        if exist(locks{k}, 'file') || isfolder(locks{k})
            error('PMUTF1:SourceLocked', 'Source model is locked: %s', locks{k});
        end
    end
end

function digest = file_sha256(path)
    hash = java.security.MessageDigest.getInstance('SHA-256');
    stream = java.io.FileInputStream(java.io.File(path));
    streamCleanup = onCleanup(@() stream.close()); %#ok<NASGU>
    channel = stream.getChannel();
    buffer = java.nio.ByteBuffer.allocate(1024 * 1024);
    while channel.read(buffer) ~= -1
        buffer.flip();
        hash.update(buffer);
        buffer.clear();
    end
    digest = lower(reshape(dec2hex(typecast(hash.digest(), 'uint8'), 2).', 1, []));
end

function atomic_save_new(path, payload)
    if exist(path, 'file')
        error('PMUTF1:OutputExists', 'Refusing to replace an existing snapshot: %s', path);
    end
    temporary = [path '.partial.mat'];
    save(temporary, '-struct', 'payload', '-v7');
    [ok, message] = movefile(temporary, path);
    if ~ok
        error('PMUTF1:OutputFinalizeFailed', 'Cannot finalize snapshot: %s', message);
    end
end

function write_report(root, report)
    path = fullfile(root, 'export_report.json');
    fid = fopen(path, 'w', 'n', 'UTF-8');
    if fid < 0
        error('PMUTF1:ReportWriteFailed', 'Cannot write export report.');
    end
    closer = onCleanup(@() fclose(fid)); %#ok<NASGU>
    fprintf(fid, '%s\n', jsonencode(report));
end

function found = has_tag(tags, target)
    found = false;
    for k = 1:numel(tags)
        if strcmp(char(tags(k)), target)
            found = true;
            return;
        end
    end
end

function cleanup_model(tag)
    try
        javaMethod('remove', 'com.comsol.model.util.ModelUtil', tag);
    catch
    end
end
