function smoke_pathway_a(port, mph_path, out_json)
%SMOKE_PATHWAY_A  验证「A 通路」：COMSOL LiveLink for MATLAB + mphserver。
%
%   A 通路 = 通过 LiveLink for MATLAB 连接到已运行的 comsolmphserver，
%   用官方 API 加载模型、读取模型结构并求解。它是 WORKING_PLAN.md 4.1 节
%   三条通路中的首选，本脚本的目的就是**实测**其可用性并留下机器可读证据。
%
%   用法：
%     set MEMS_SMOKE_MODEL=<模型副本路径>
%     matlab -batch "smoke_pathway_a(2036, 'D:\COMSOL64\Multiphysics\mli', 'work\reports\pathway_a.json')"
%
%   约定：
%     - 只加载**工作区里的模型副本**，绝不改动生产模型（AGENTS.md 第 4 节）。
%     - 无论成功失败都写出证据文件：失败本身也是结论。
%     - 每一步单独 try/catch，局部失败不会掩盖已达成的结论。

if nargin < 1 || isempty(port), port = 2036; end
if nargin < 2 || isempty(mph_path), mph_path = 'D:\COMSOL64\Multiphysics\mli'; end
if nargin < 3 || isempty(out_json), out_json = 'work\reports\pathway_a.json'; end

evidence = struct();
evidence.generated_at = char(datetime('now', 'Format', 'yyyy-MM-dd''T''HH:mm:ss'));
evidence.pathway = 'A: LiveLink for MATLAB + mphserver';
evidence.port = port;
evidence.mph_path = mph_path;
evidence.matlab_version = version;
evidence.ok = false;
evidence.steps = {};
evidence.errors = {};

try
    % 1) 挂载 LiveLink 并连接**已运行**的 mphserver（不重复启动服务）
    addpath(mph_path);
    log_step(sprintf('addpath 完成: %s', mph_path));
    import com.comsol.model.*
    import com.comsol.model.util.*
    mphstart(port);
    log_step(sprintf('mphstart(%d) 成功：已连接到运行中的 mphserver', port));

    % 2) 加载模型副本
    model_path = getenv('MEMS_SMOKE_MODEL');
    assert(~isempty(model_path), 'MEMS_SMOKE_MODEL 未设置');
    assert(isfile(model_path), '模型文件不存在: %s', model_path);
    model = ModelUtil.load('SmokeModel', model_path);
    log_step(sprintf('ModelUtil.load 成功: %s', model_path));

    % 3) 只读探测模型结构（每项独立容错）
    evidence.structure = probe(model);

    % 4) 求解第一个研究
    study_tags = getfield_safe(evidence.structure, 'study_tags', {});
    if ~isempty(study_tags)
        t0 = tic;
        try
            model.study(study_tags{1}).run();
            evidence.solve_seconds = toc(t0);
            evidence.solve_ok = true;
            log_step(sprintf('研究 %s 求解成功，耗时 %.1f s', study_tags{1}, evidence.solve_seconds));
        catch solve_err
            evidence.solve_ok = false;
            evidence.errors{end+1} = sprintf('solve: %s', solve_err.message);
            log_step(sprintf('研究求解失败: %s', solve_err.message));
        end
    else
        log_step('模型没有研究（study），跳过求解');
    end

    evidence.ok = true;
    try
        ModelUtil.clear();
    catch
    end
catch err
    evidence.errors{end+1} = sprintf('%s: %s', err.identifier, err.message);
    fprintf('[pathwayA][ERROR] %s: %s\n', err.identifier, err.message);
end

out_dir = fileparts(out_json);
if ~isempty(out_dir) && ~isfolder(out_dir), mkdir(out_dir); end
fid = fopen(out_json, 'w', 'n', 'UTF-8');
fprintf(fid, '%s', jsonencode(evidence, 'PrettyPrint', true));
fclose(fid);
fprintf('[pathwayA] 证据已写入 %s (ok=%d)\n', out_json, evidence.ok);

if ~evidence.ok
    exit(2);
end

    % ---- 嵌套辅助函数（共享 evidence 工作区）----
    function log_step(msg)
        evidence.steps{end+1} = msg;
        fprintf('[pathwayA] %s\n', msg);
    end
end

function s = probe(model)
%PROBE  只读探测：参数 / 组件 / 物理场 / 研究。任一项失败只记录不中断。
s = struct();
s.param_names = probe_cells(@() model.param.varnames());
s.component_tags = probe_cells(@() model.modelNode.tags());
s.study_tags = probe_cells(@() model.study.tags());

physics = {};
try
    comp_tags = s.component_tags;
    for c = 1:numel(comp_tags)
        comp = model.modelNode(comp_tags{c});
        phys_tags = comp.physics.tags();
        for p = 1:numel(phys_tags)
            phys = comp.physics(phys_tags{p});
            physics{end+1} = sprintf('%s/%s:%s', comp_tags{c}, phys_tags{p}, char(phys.getType())); %#ok<AGROW>
        end
    end
catch err
    physics{end+1} = sprintf('(物理场探测失败: %s)', err.message);
end
s.physics = physics;
fprintf('[pathwayA] 参数 %d 个 / 组件 %d 个 / 研究 %d 个 / 物理场 %d 个\n', ...
    numel(s.param_names), numel(s.component_tags), numel(s.study_tags), numel(physics));
end

function out = probe_cells(fn)
%PROBE_CELLS  调用可能不存在的 API，失败返回空 cell。
try
    out = cell(fn());
catch
    out = {};
end
end

function value = getfield_safe(s, name, default)
if isstruct(s) && isfield(s, name) && ~isempty(s.(name))
    value = s.(name);
else
    value = default;
end
end
