# Mixtape Bug Hunt Submission

## AI usage

I used Codex as a debugging partner while reading the project. The main help was for orientation: summarizing what the route files and service files were responsible for, tracing which service each endpoint used, and comparing the working playlist notification path with the missing rating notification path. I still checked the actual code myself by reading the files and running tests, because the assignment bugs depend on exact details like date comparisons, query joins, and list slicing.

## Codebase map

`app.py` creates the Flask app, configures SQLAlchemy, registers the route blueprints, and creates the database tables.

`models.py` defines the database shape. The main models are `User`, `Song`, `Rating`, `Playlist`, `ListeningEvent`, `Notification`, and `Tag`. There are also association tables for friendships, song tags, and playlist entries. The playlist entry table is important because it stores song order with a `position` column.

The `routes/` folder is the API layer. Each route gets request data, calls a service function, and formats the JSON response. For example, `routes/songs.py` handles search, rating, and listening endpoints. `routes/playlists.py` handles playlist creation and playlist song retrieval. `routes/users.py` exposes user profile, streak, and notification endpoints. `routes/feed.py` exposes the listening-now and activity feeds.

The `services/` folder contains the business logic where the bugs live. `streak_service.py` updates listening streaks. `feed_service.py` builds the friends listening-now feed. `search_service.py` searches songs. `notification_service.py` creates notifications and saves ratings. `playlist_service.py` creates playlists and returns ordered playlist songs.

`seed_data.py` creates realistic users, friendships, songs, tags, playlists, listening events, and sample notifications. The `tests/` folder has regression tests for the buggy service behavior.

Data flow example - rating a song: a client sends `POST /songs/<song_id>/rate` with `user_id` and `score`. The route in `routes/songs.py` validates those fields and calls `notification_service.rate_song()`. That service loads the `Song` and `User`, creates or updates a `Rating`, commits it, and should also create a `song_rated` notification for the original sharer when another user rates their song. The route returns the saved rating as JSON.

Pattern I noticed: routes stay thin and services do the real work. Most services load models with `db.session.get()`, check error cases, then commit only after changing the database.

## Root cause analysis

### Issue #1 - My listening streak keeps resetting

RCA will be completed with the fix commit.

### Issue #2 - Friends Listening Now shows people from yesterday

RCA will be completed with the fix commit.

### Issue #3 - The same song keeps showing up twice in search

RCA will be completed with the fix commit.

### Issue #4 - I got notified when a friend added my song to a playlist but not when they rated it

RCA will be completed with the fix commit.

### Issue #5 - The last song in a playlist never shows up

RCA will be completed with the fix commit.
