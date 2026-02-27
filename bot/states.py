"""Conversation state constants for the 7-step post flow."""

(
    SELECTING_PLATFORMS,   # Step 1 – platform checkboxes
    SELECTING_TOPIC,       # Step 2 – type topic or pick repo
    SELECTING_REPO,        # Step 2b – user picks a suggested repo
    SELECTING_IMAGE,       # Step 3 – image choice
    UPLOADING_IMAGE,       # Step 3b – waiting for user to upload photo
    SELECTING_IMG_STYLE,   # Step 3c – AI image style picker
    REVIEWING_CONTENT,     # Step 4/5 – preview + edit loop
    EDITING_CONTENT,       # Step 5 – user types edit instruction
    SELECTING_SCHEDULE,    # Step 6 – now or schedule?
    ENTERING_DATETIME,     # Step 6b – user enters date/time string
    UPDATING_STYLE,        # /style command flow
) = range(11)
