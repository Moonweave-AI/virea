"""Build model completion fixtures using atomic, explicitly allocated phases."""


def native_plan(
    *,
    actions,
    executors,
    starts,
    objective_groups,
    ending=None,
    ending_executor=None,
    ending_seconds=None,
    end_state="hold",
    **unused,
):
    return dict(
        phases=[
            dict(objectives=group, start=start, executor=executor, action=action)
            for group, start, executor, action in zip(
                objective_groups, starts, executors, actions, strict=True
            )
        ],
        recovery=dict(
            executor=ending_executor,
            goal=ending,
            seconds=ending_seconds,
            reason="Complete the adopted activity",
        )
        if ending
        else None,
        end_state=end_state,
    )
