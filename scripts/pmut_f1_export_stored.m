function export = pmut_f1_export_stored(modelPath, manifestPath, outputRoot, maxModelBytes)
%PMUT_F1_EXPORT_STORED 清单驱动导出已保存的复声压解，不执行任何求解。
% export = pmut_f1_export_stored(modelPath, manifestPath, outputRoot [, maxModelBytes])
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
    export = struct('schema', 'memsharness.pmut_f1_stored_export/v0', ...
        'status', 'running', 'phase', 'hash_start', 'source_model', modelPath, 'source_model_sha256', '', ...
        'manifest_path', manifestPath, 'manifest_sha256', '', ...
        'source_before', before, 'source_after', [], 'source_unchanged', false, ...
        'dataset', manifest.dataset, 'field_expression', manifest.field_expression, ...
        'requested', numel(manifest.cases), 'completed', 0, 'cases', {{}}, ...
        'mode_identity', 'unverified', 'training_ready', false, ...
        'missing_operator_inputs', {{'geometry_topology', 'material_fields', ...
            'boundary_condition_values_and_tags', 'excitation_and_losses'}}, ...
        'point_reference_source', 'scalar_table_reference_not_field_node', ...
        'point_reference_same_model_verified', false, 'error', '');
    try
        % SHA256 来自当前文件实际字节。大小/mtime 同时防止哈希过程中源文件变化。
        write_report(outputRoot, export);
        fprintf('PMUTF1 hash_start source_bytes=%.0f cases=%d\n', before.size_bytes, export.requested);
        export.source_model_sha256 = file_sha256(modelPath);
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
        pressureExpr = {'x', 'y', 'z', manifest.field_expression, ...
            'freq', 'x_scale', 'N_w_te1', 'N_w_te2'};
        for index = 1:numel(manifest.cases)
            selected = manifest.cases(index);
            export.phase = 'exporting_case';
            export.active_case_id = selected.case_id;
            write_report(outputRoot, export);
            node.set('expr', pressureExpr);
            [rr, ii] = eval_one(node, selected.outer_solnum, selected.inner_solnum, 8);
            validate_solution_columns(rr, ii, selected);
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
            [dom, domAvailable, domMessage] = read_optional_dom(node, selected, xyz_m);
            pointReference = struct('xyz_m', [0, 0, -1e-5], ...
                'p_real_Pa', selected.p_point_real_Pa, 'p_imag_Pa', selected.p_point_imag_Pa, ...
                'source_type', 'scalar_table_reference_not_field_node', ...
                'source_table_sha256', selected.source_table_sha256, ...
                'source_table_row_1based', selected.source_table_row_1based, ...
                'table_hash_verification', 'manifest_declared_not_recomputed', ...
                'pressure_consistent_with_stored_solution', true, ...
                'comparison_rtol', 1e-6, 'comparison_atol_Pa', 1e-9, ...
                'same_source_model_verified', false);
            sample = struct('schema', 'memsharness.pmut_f1_stored_field/v0', ...
                'case_id', selected.case_id, 'xyz_m', xyz_m, ...
                'x_m', xyz_m(1, :), 'y_m', xyz_m(2, :), 'z_m', xyz_m(3, :), ...
                'p_total_Pa', p_total_Pa, 'p_finite_mask', p_finite_mask, ...
                'dom_available', domAvailable, 'dom_message', domMessage, ...
                'frequency_Hz', selected.frequency_Hz, 'x_scale', selected.x_scale, ...
                'N_w_te1', selected.N_w_te1, 'N_w_te2', selected.N_w_te2, ...
                'outer_solnum', selected.outer_solnum, 'inner_solnum', selected.inner_solnum, ...
                'solution_identity_verified', true, 'mode_identity', 'unverified', ...
                'solution_identity_verification_scope', 'requested_parameters_frequency_and_point_pressure_not_physics_equivalence', ...
                'source_type', 'simulation', 'source_model', modelPath, ...
                'source_model_sha256', export.source_model_sha256, ...
                'source_hash_verification', 'computed_from_file_bytes', ...
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
                'dom_available', domAvailable, 'mode_identity', 'unverified');
            export.completed = index;
            export.phase = 'case_done';
            write_report(outputRoot, export);
            fprintf('PMUTF1 case_done %d/%d case_id=%s n_points=%d\n', ...
                export.completed, export.requested, selected.case_id, size(xyz_m, 2));
        end
        export.source_after = file_stamp(modelPath);
        assert_source_unchanged(modelPath, before);
        assert_no_lock(modelPath);
        export.source_unchanged = true;
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
    if ~strcmp(manifest.schema, 'memsharness.pmut_f1_export_manifest/v0') || ...
            ~strcmp(manifest.dataset, 'dset3') || ~strcmp(manifest.field_expression, 'acpr.p_t')
        error('PMUTF1:InvalidManifest', 'Manifest schema/dataset/field expression is not supported.');
    end
    if ~isnumeric(manifest.observation_xyz_m) || ...
            ~isequal(reshape(manifest.observation_xyz_m, 1, []), [0, 0, -1e-5])
        error('PMUTF1:InvalidManifest', 'Observation must be model-global (0,0,-10 um).');
    end
    if ~isstruct(manifest.cases) || isempty(manifest.cases)
        error('PMUTF1:InvalidManifest', 'At least one case is required.');
    end
    fields = {'case_id', 'x_scale', 'N_w_te1', 'N_w_te2', 'frequency_Hz', ...
        'outer_solnum', 'inner_solnum', 'p_point_real_Pa', 'p_point_imag_Pa', ...
        'source_table_sha256', 'source_table_row_1based', 'mode_identity'};
    if ~all(isfield(manifest.cases, fields))
        error('PMUTF1:InvalidManifest', 'A case is missing required fields.');
    end
    ids = cell(1, numel(manifest.cases));
    numericFields = {'x_scale', 'N_w_te1', 'N_w_te2', 'frequency_Hz', ...
        'outer_solnum', 'inner_solnum', 'p_point_real_Pa', 'p_point_imag_Pa', 'source_table_row_1based'};
    integerFields = {'N_w_te1', 'N_w_te2', 'outer_solnum', 'inner_solnum', 'source_table_row_1based'};
    for index = 1:numel(manifest.cases)
        selected = manifest.cases(index);
        if ~ischar(selected.case_id) || isempty(regexp(selected.case_id, '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$', 'once'))
            error('PMUTF1:InvalidManifest', 'case_id must be a safe, unique filename stem.');
        end
        ids{index} = selected.case_id;
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
        values = rr(index + 4, :);
        imaginary = ii(index + 4, :);
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

function [dom, available, message] = read_optional_dom(node, selected, xyz)
    dom = [];
    available = false;
    message = '';
    try
        node.set('expr', {'x', 'y', 'z', 'dom', 'freq', 'x_scale', 'N_w_te1', 'N_w_te2'});
        [rr, ii] = eval_one(node, selected.outer_solnum, selected.inner_solnum, 8);
        validate_solution_columns(rr, ii, selected);
        if ~isequal(rr(1:3, :), xyz)
            error('PMUTF1:DomainCoordinatesMismatch', 'Domain IDs do not share pressure evaluation coordinates.');
        end
        dom = rr(4, :);
        finite = isfinite(dom);
        if ~any(finite) || any(dom(finite) < 1 | dom(finite) ~= fix(dom(finite)))
            error('PMUTF1:InvalidDomainIds', 'No valid integer domain ID field.');
        end
        available = true;
    catch err
        if any(strcmp(err.identifier, {'PMUTF1:SolutionIdentityMismatch', 'PMUTF1:IndexReadbackMismatch'}))
            rethrow(err);
        end
        dom = [];
        message = [err.identifier ': ' err.message];
    end
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
